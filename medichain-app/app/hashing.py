"""Hashing kanonik. Murni stdlib agar mudah diuji dan diaudit.

Hash rekam = SHA-256(salt || JSON kanonik). Salt acak per rekam disimpan off-chain,
sehingga hash on-chain tidak bisa ditebak lewat serangan kamus pada data berentropi rendah.
Jika penyerang mengubah salt di basis data, hash ikut berubah dan terdeteksi.
"""
import hashlib
import hmac
import json
import os
from typing import Optional, Sequence

GENESIS = "0" * 64


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def new_salt() -> str:
    return os.urandom(16).hex()


def hash_record(salt: str, fields: dict) -> str:
    return hashlib.sha256(bytes.fromhex(salt) + canonical_json(fields)).hexdigest()


def hash_ecg(salt: str, fs: int, samples: Sequence[float]) -> str:
    quantized = [int(round(float(x) * 1000)) for x in samples]  # bebas ambiguitas float
    return hashlib.sha256(bytes.fromhex(salt) + canonical_json({"fs": fs, "s": quantized})).hexdigest()


def chain_key(record_id: str) -> str:
    """Identifier on-chain (bytes32 hex). UUID rekam tidak ditulis langsung ke blockchain."""
    return hashlib.sha256(record_id.encode()).hexdigest()


def role_hash(role: str) -> str:
    return hashlib.sha256(("medichain.role." + role).encode()).hexdigest()


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ---- audit log berantai (tamper-evident) ----
def entry_hash(prev_hash: str, entry: dict) -> str:
    return hashlib.sha256(prev_hash.encode() + canonical_json(entry)).hexdigest()


def verify_audit_rows(rows: Sequence[dict]) -> Optional[int]:
    """rows berurutan, tiap item: {'id','prev_hash','hash', ...field entry}.
    Mengembalikan id baris pertama yang rusak, atau None bila rantai utuh."""
    prev = GENESIS
    for r in rows:
        entry = {k: v for k, v in r.items() if k not in ("id", "prev_hash", "hash")}
        if r["prev_hash"] != prev or entry_hash(prev, entry) != r["hash"]:
            return r["id"]
        prev = r["hash"]
    return None
