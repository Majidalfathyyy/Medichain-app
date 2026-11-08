"""Durable, idempotent outbox for writes spanning SQL and a public blockchain."""
import threading
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .chain import ChainClient
from .config import settings
from .db import ChainOperation, TimelineAnchor
from .hashing import same

_processor_lock = threading.Lock()


def enqueue_record_register(db: Session, record_id: str, record_key: str, hash_record: str,
                            hash_ecg: str, actor: str, actor_role: str | None,
                            version: int = 1) -> ChainOperation:
    item = ChainOperation(operation="register", record_id=record_id, record_key=record_key,
                          hash_record=hash_record, hash_ecg=hash_ecg, expected_version=version,
                          actor=actor, actor_role=actor_role)
    db.add(item)
    return item


def enqueue_record_update(db: Session, record_id: str, record_key: str, hash_record: str,
                          hash_ecg: str, expected_version: int, actor: str,
                          actor_role: str | None) -> ChainOperation:
    item = ChainOperation(operation="update", record_id=record_id, record_key=record_key,
                          hash_record=hash_record, hash_ecg=hash_ecg, expected_version=expected_version,
                          actor=actor, actor_role=actor_role)
    db.add(item)
    return item


def enqueue_access(db: Session, record_id: str, record_key: str, role_hash: str,
                   allowed: bool, actor: str, actor_role: str | None) -> ChainOperation:
    item = ChainOperation(operation="access", record_id=record_id, record_key=record_key,
                          role_hash=role_hash, allowed=allowed, actor=actor, actor_role=actor_role)
    db.add(item)
    return item


def enqueue_timeline_anchor(db: Session, record_id: str, record_key: str,
                            timeline_hash: str, actor: str, actor_role: str | None) -> TimelineAnchor:
    existing = db.scalar(select(TimelineAnchor).where(
        TimelineAnchor.patient_id == record_id,
        TimelineAnchor.timeline_hash == timeline_hash,
        TimelineAnchor.status.in_(("pending", "confirmed")),
    ).order_by(TimelineAnchor.id.desc()).limit(1))
    if existing:
        return existing
    anchor = TimelineAnchor(patient_id=record_id, timeline_hash=timeline_hash, status="pending")
    db.add(anchor)
    db.flush()
    db.add(ChainOperation(operation="timeline", record_id=record_id, record_key=record_key,
                          hash_record=timeline_hash, expected_version=anchor.id,
                          actor=actor, actor_role=actor_role))
    return anchor


def process_pending(db: Session, chain: ChainClient, limit: int = 25) -> int:
    """Process committed operations in order; repeated calls safely resume after crashes."""
    with _processor_lock:
        completed = 0
        for _ in range(max(1, min(limit, 100))):
            item = db.scalar(
                select(ChainOperation).where(ChainOperation.status == "pending")
                .order_by(ChainOperation.id).limit(1).with_for_update()
            )
            if item is None:
                break
            tx_hash = None
            try:
                if item.operation == "register":
                    current = chain.get(item.record_key)
                    target_version = item.expected_version or 1
                    if current is None:
                        tx = chain.register(item.record_key, item.hash_record, item.hash_ecg, target_version)
                        tx_hash = tx.tx_hash
                    elif current.version == target_version and same(current.hash_record, item.hash_record) and same(current.hash_ecg, item.hash_ecg):
                        pass  # Chain accepted it before a process restart interrupted the SQL confirmation.
                    else:
                        raise RuntimeError("Kunci rekam sudah terdaftar dengan hash atau versi berbeda")
                elif item.operation == "update":
                    current = chain.get(item.record_key)
                    target_version = (item.expected_version or 0) + 1
                    if current is None:
                        raise RuntimeError("Rekam belum terdaftar di blockchain")
                    if current.version == target_version and same(current.hash_record, item.hash_record) and same(current.hash_ecg, item.hash_ecg):
                        pass  # Chain update succeeded before the SQL confirmation was interrupted.
                    elif current.version == item.expected_version:
                        tx = chain.update(item.record_key, item.hash_record, item.hash_ecg)
                        tx_hash = tx.tx_hash
                    else:
                        raise RuntimeError(f"Versi chain {current.version} tidak sesuai dengan versi dasar {item.expected_version}")
                elif item.operation == "access":
                    already_allowed = chain.has_access(item.record_key, item.role_hash)
                    if already_allowed != bool(item.allowed):
                        fn = chain.grant if item.allowed else chain.revoke
                        tx = fn(item.record_key, item.role_hash)
                        tx_hash = tx.tx_hash
                elif item.operation == "timeline":
                    if not item.hash_record:
                        raise RuntimeError("Hash timeline kosong")
                    tx = chain.log_access(item.record_key, item.hash_record)
                    tx_hash = tx.tx_hash
                    anchor = db.get(TimelineAnchor, item.expected_version) if item.expected_version else None
                    if anchor:
                        from datetime import datetime
                        anchor.status = "confirmed"
                        anchor.tx_hash = tx_hash
                        anchor.confirmed_at = datetime.utcnow()
                else:
                    raise RuntimeError(f"Operasi outbox tidak dikenal: {item.operation}")
                item.status = "confirmed"
                item.tx_hash = tx_hash
                item.last_error = ""
                action = {"register": "RecordRegisteredOnChain", "update": "RecordUpdatedOnChain",
                          "access": "AccessPermissionOnChain", "timeline": "TimelineAnchoredOnChain"}[item.operation]
                audit.append(db, item.actor, item.actor_role, action, item.record_id,
                             "ok", item.operation, tx_hash)
                db.commit()
                completed += 1
            except Exception as exc:
                db.rollback()
                item = db.get(ChainOperation, item.id)
                if item is None:
                    break
                item.attempts += 1
                raw_error = str(exc)
                safe_error = raw_error.replace(settings.rpc_url, "[RPC_URL]") if settings.rpc_url else raw_error
                item.last_error = safe_error[:500]
                db.commit()
                break  # Keep order; the next call retries this operation before later ones.
        return completed
