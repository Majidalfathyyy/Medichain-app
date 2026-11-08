"""Audit log berantai: setiap baris memuat hash baris sebelumnya, sehingga
pengubahan atau penghapusan baris di tengah rantai dapat terdeteksi."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import AuditLog
from .hashing import GENESIS, entry_hash, verify_audit_rows

FIELDS = ("ts", "actor", "role", "action", "record_id", "outcome", "detail", "tx_hash")


def append(db: Session, actor: str, role: Optional[str], action: str, record_id: Optional[str],
           outcome: str, detail: str = "", tx_hash: Optional[str] = None) -> AuditLog:
    last = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()).limit(1).with_for_update())
    prev = last.hash if last else GENESIS
    entry = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "actor": actor, "role": role,
             "action": action, "record_id": record_id, "outcome": outcome, "detail": detail[:500], "tx_hash": tx_hash}
    row = AuditLog(**entry, prev_hash=prev, hash=entry_hash(prev, entry))
    db.add(row)
    db.flush()
    return row


def rows(db: Session):
    return db.scalars(select(AuditLog).order_by(AuditLog.id)).all()


def verify_chain(db: Session) -> Optional[int]:
    data = [{"id": r.id, "prev_hash": r.prev_hash, "hash": r.hash, **{f: getattr(r, f) for f in FIELDS}} for r in rows(db)]
    return verify_audit_rows(data)
