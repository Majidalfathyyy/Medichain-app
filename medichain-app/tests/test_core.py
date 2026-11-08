"""Uji logika inti tanpa framework web/DB (hanya stdlib + PyJWT). Jalankan: pytest -q  atau  python -m tests.test_core"""
import time

import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.chain import MockChain
from app.chain_ops import enqueue_record_register, process_pending
from app.db import Base, ChainOperation
from app.hashing import GENESIS, chain_key, entry_hash, hash_ecg, hash_record, new_salt, same, verify_audit_rows
from app.security import RateLimiter, create_token, decode_token, hash_password, verify_password
from app.services import make_patient_ecg

REC = {"id": "r1", "age": 54, "sex": "L", "history": "Hipertensi", "diagnosis": "AF", "notes": "Kontrol"}
ECG = [0.0, 0.1, 1.2, -0.3] * 50


def test_hash_deterministik_dan_sensitif():
    s = new_salt()
    assert hash_record(s, REC) == hash_record(s, dict(reversed(list(REC.items()))))  # urutan key tak berpengaruh
    assert hash_record(s, REC) != hash_record(s, {**REC, "diagnosis": "Normal"})
    assert hash_record(s, REC) != hash_record(new_salt(), REC)                        # salt berbeda -> hash berbeda
    e = list(ECG); e[10] += 0.001
    assert hash_ecg(s, 250, ECG) != hash_ecg(s, 250, e)


def test_alur_register_verify_tamper():
    chain, key, sr, se = MockChain(), chain_key("r1"), new_salt(), new_salt()
    chain.register(key, hash_record(sr, REC), hash_ecg(se, 250, ECG))
    on = chain.get(key)
    assert same(hash_record(sr, REC), on.hash_record) and same(hash_ecg(se, 250, ECG), on.hash_ecg)
    tampered = {**REC, "diagnosis": "Normal"}
    assert not same(hash_record(sr, tampered), on.hash_record)       # tampering rekam terdeteksi
    e = list(ECG); e[100] = 1.5
    assert not same(hash_ecg(se, 250, e), on.hash_ecg)               # tampering ECG terdeteksi
    assert not same(hash_record(new_salt(), REC), on.hash_record)    # salt diganti pun terdeteksi
    chain.update(key, hash_record(sr, tampered), on.hash_ecg)
    assert chain.get(key).version == 2


def test_mockchain_tolak_duplikat_dan_unknown():
    c = MockChain(); c.register("a" * 64, "1" * 64, "2" * 64)
    for fn in (lambda: c.register("a" * 64, "1" * 64, "2" * 64), lambda: c.update("b" * 64, "1" * 64, "2" * 64)):
        try:
            fn(); assert False
        except RuntimeError:
            pass
    assert c.get("b" * 64) is None


def test_outbox_mencoba_ulang_setelah_chain_gagal():
    # The test only needs an isolated database connection; in-memory SQLite
    # avoids platform-specific filesystem temp-directory permissions on Windows.
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    chain = MockChain()
    original_get = chain.get
    failed_once = False

    def unreliable_get(key):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise ConnectionError("node unavailable")
        return original_get(key)

    chain.get = unreliable_get
    try:
        with Session(engine) as db:
            operation = enqueue_record_register(
                db, "synthetic-record", "a" * 64, "b" * 64, "c" * 64, "tester", "admin"
            )
            db.commit()
            operation_id = operation.id

            assert process_pending(db, chain) == 0
            db.expire_all()
            operation = db.get(ChainOperation, operation_id)
            assert operation.status == "pending" and operation.attempts == 1
            assert "node unavailable" in operation.last_error

            assert process_pending(db, chain) == 1
            db.expire_all()
            operation = db.get(ChainOperation, operation_id)
            assert operation.status == "confirmed" and operation.attempts == 1
            assert chain.get("a" * 64).hash_record == "b" * 64
            assert process_pending(db, chain) == 0
    finally:
        engine.dispose()


def test_audit_chain_deteksi_perubahan_dan_penghapusan():
    rows, prev = [], GENESIS
    for i in range(1, 6):
        e = {"ts": f"t{i}", "actor": "u", "role": "dokter", "action": "READ", "record_id": "r", "outcome": "ok", "detail": "", "tx_hash": None}
        h = entry_hash(prev, e); rows.append({"id": i, "prev_hash": prev, "hash": h, **e}); prev = h
    assert verify_audit_rows(rows) is None
    bad = [dict(r) for r in rows]; bad[2]["outcome"] = "denied"
    assert verify_audit_rows(bad) == 3
    assert verify_audit_rows(rows[:2] + rows[3:]) == 4                # baris tengah dihapus


def test_password_dan_jwt():
    h = hash_password("rahasia-panjang-123")
    assert verify_password("rahasia-panjang-123", h) and not verify_password("salah", h) and not verify_password("x", "bukan-hash")
    assert decode_token(create_token(7))["sub"] == "7"
    for bad in (create_token(1) + "x", jwt.encode({"sub": "1"}, "kunci-lain", algorithm="HS256"),
                jwt.encode({"sub": "1", "iat": 1, "exp": 2, "iss": "medichain"}, "x" * 40, algorithm="HS256")):
        try:
            decode_token(bad); assert False
        except jwt.PyJWTError:
            pass
    assert jwt.decode(create_token(1), options={"verify_signature": False})["exp"] > time.time()


def test_rate_limiter():
    r = RateLimiter(3, 60)
    assert [r.allow("k") for _ in range(4)] == [True, True, True, False] and r.allow("lain")


def test_ecg_sintetis_deterministik_bervariasi_dan_mengandung_morfologi():
    first = make_patient_ecg(412)
    repeated = make_patient_ecg(412)
    another_patient = make_patient_ecg(413)
    assert len(first) == 250 * 8
    assert first == repeated
    assert first != another_patient
    assert max(first) > 0.8  # kompleks QRS
    assert min(first) < -0.08  # gelombang Q/S
    assert len(set(first)) > 500  # baseline dan noise sintetis


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok  ", n)
