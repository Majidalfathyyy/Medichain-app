"""Logika bisnis: pembuatan rekam, pembaruan sah, dan pengecekan integritas."""
import json
import math
import random
import uuid

from sqlalchemy.orm import Session

from . import audit
from .chain_ops import enqueue_access, enqueue_record_register
from .chain import ChainClient
from .db import Access, Biosignal, Record, User
from .hashing import chain_key, hash_ecg, hash_record, new_salt, role_hash, same
from .schemas import RecordIn


def make_patient_ecg(seed: int, fs: int = 250, seconds: int = 8) -> list[float]:
    """Buat ECG lead II sintetis yang deterministik dan berbeda untuk tiap pasien demo.

    Bentuk P-QRS-T, variasi interval RR, pergeseran garis dasar, dan derau kecil
    membuatnya tampak seperti monitor, tetapi sinyal ini bukan untuk diagnosis.
    """
    rng = random.Random(seed)
    heart_rate = rng.randint(62, 104)
    mean_rr = 60.0 / heart_rate
    phase = rng.random() * math.tau
    amplitude = rng.uniform(.9, 1.1)
    t_peak = rng.uniform(.24, .32)
    r_peaks = []
    next_peak = rng.uniform(.45, .57)
    while next_peak < seconds + .5:
        r_peaks.append(next_peak)
        next_peak += mean_rr + rng.uniform(-.035, .035)

    values = []
    for i in range(fs * seconds):
        t = i / fs
        signal = .025 * math.sin(math.tau * .25 * t + phase) + .009 * math.sin(math.tau * .08 * t + phase * .6)
        for peak in r_peaks:
            delta = t - peak
            if delta < -.45 or delta > .65:
                continue
            gauss = lambda center, width, height: height * math.exp(-((delta - center) ** 2) / (2 * width * width))
            signal += amplitude * (
                gauss(-.19, .035, .12)       # gelombang P
                + gauss(-.038, .009, -.13)   # Q
                + gauss(0, .011, 1.0)        # R
                + gauss(.035, .012, -.24)    # S
                + gauss(t_peak, .075, .28)   # gelombang T
            )
        signal += .0025 * math.sin(math.tau * 50 * t + phase) + rng.gauss(0, .0045)
        values.append(round(signal, 4))
    return values


def record_fields(r: Record) -> dict:
    return {"id": r.id, "age": r.age, "sex": r.sex, "history": r.history, "diagnosis": r.diagnosis, "notes": r.notes}


def local_hashes(db: Session, r: Record):
    b = db.get(Biosignal, r.id)
    return hash_record(r.salt, record_fields(r)), hash_ecg(b.salt, b.fs, json.loads(b.samples))


def create_record(db: Session, chain: ChainClient, actor: User, data: RecordIn) -> Record:
    rec = Record(id=str(uuid.uuid4()), pseudo_id="PSN-" + uuid.uuid4().hex[:8].upper(), age=data.age, sex=data.sex,
                 history=data.history, diagnosis=data.diagnosis, notes=data.notes, salt=new_salt(), version=1)
    ecg = Biosignal(record_id=rec.id, fs=data.ecg.fs, samples=json.dumps([round(x, 3) for x in data.ecg.samples]), salt=new_salt())
    db.add(rec)
    db.flush()
    db.add(ecg)
    for role, allowed in (("dokter", True), ("auditor", True), ("pasien", False)):
        db.add(Access(record_id=rec.id, role=role, allowed=allowed))
    db.flush()
    hr, he = local_hashes(db, rec)
    key = chain_key(rec.id)
    enqueue_record_register(db, rec.id, key, hr, he, actor.username, actor.role, rec.version)
    for role in ("dokter", "auditor"):  # izin awal dicatat on-chain, selaras dengan tabel access
        enqueue_access(db, rec.id, key, role_hash(role), True, actor.username, actor.role)
    audit.append(db, actor.username, actor.role, "RecordRegistered", rec.id, "pending",
                 "versi 1 menunggu konfirmasi blockchain")
    return rec


def check_integrity(db: Session, chain: ChainClient, rec: Record) -> dict:
    hr, he = local_hashes(db, rec)
    on = chain.get(chain_key(rec.id))
    if on is None:
        return {"status": "not_registered", "record_ok": False, "ecg_ok": False, "local": {"hash_record": hr, "hash_ecg": he}, "onchain": None}
    rec_ok, ecg_ok = same(hr, on.hash_record), same(he, on.hash_ecg)
    version_ok = on.version == rec.version
    status = "modified" if not rec_ok or not ecg_ok else ("version_mismatch" if not version_ok else "valid")
    return {"status": status, "record_ok": rec_ok, "ecg_ok": ecg_ok, "version_ok": version_ok,
            "local": {"hash_record": hr, "hash_ecg": he},
            "onchain": {"hash_record": on.hash_record, "hash_ecg": on.hash_ecg, "version": on.version, "timestamp": on.timestamp}}
