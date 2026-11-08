"""Patient data deletion with an immutable blockchain/audit tombstone."""
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from . import audit
from .chain_ops import enqueue_access
from .chain import ChainClient
from .db import (
    Access,
    Appointment,
    AppointmentRequest,
    AuditLog,
    Biosignal,
    ChainOperation,
    CareEpisode,
    ClinicalObservation,
    Invoice,
    PatientActivity,
    PatientCare,
    PatientProfile,
    RecordShare,
    RecordShareAccess,
    Record,
    TimelineAnchor,
    User,
)
from .hashing import chain_key, role_hash
from .security import ACL_ROLES


def erase_patient_record(
    db: Session,
    chain: ChainClient,
    record_id: str,
    actor: str,
    actor_role: str | None,
) -> None:
    """Erase off-chain patient data and related rows, preserving audit/on-chain history."""
    record = db.get(Record, record_id)
    if record is None:
        return

    # Never publish a queued clinical hash after its record has been erased.
    cancelled = db.execute(
        update(ChainOperation)
        .where(ChainOperation.record_id == record_id, ChainOperation.status == "pending",
               ((ChainOperation.operation.in_(("register", "update", "timeline"))) |
                ((ChainOperation.operation == "access") & (ChainOperation.allowed.is_(True)))))
        .values(status="cancelled", last_error="Dibatalkan karena rekam pasien dihapus")
    ).rowcount or 0
    if cancelled:
        audit.append(db, actor, actor_role, "BlockchainOperationCancelled", record_id, "ok",
                     f"{cancelled} operasi pending dibatalkan saat penghapusan")

    # Persist revocations before removing ACL rows. They remain retryable even if RPC is down.
    for role in ACL_ROLES:
        enqueue_access(db, record_id, chain_key(record_id), role_hash(role), False, actor, actor_role)
        audit.append(db, actor, actor_role, "PatientAccessRevoked", record_id, "pending",
                     f"akses {role} menunggu pencabutan on-chain")

    # Delete FK dependents explicitly. This works consistently on SQLite and PostgreSQL,
    # including older SQLite files where foreign-key cascades were not enabled.
    db.execute(delete(RecordShareAccess).where(
        RecordShareAccess.share_id.in_(select(RecordShare.id).where(RecordShare.patient_id == record_id))
    ))
    dependents = (
        (PatientActivity, PatientActivity.patient_id),
        (ClinicalObservation, ClinicalObservation.patient_id),
        (AppointmentRequest, AppointmentRequest.patient_id),
        (Appointment, Appointment.patient_id),
        (Invoice, Invoice.patient_id),
        (PatientCare, PatientCare.patient_id),
        (CareEpisode, CareEpisode.patient_id),
        (PatientProfile, PatientProfile.record_id),
        (RecordShare, RecordShare.patient_id),
        (TimelineAnchor, TimelineAnchor.patient_id),
        (Biosignal, Biosignal.record_id),
        (Access, Access.record_id),
    )
    for model, foreign_key in dependents:
        db.execute(delete(model).where(foreign_key == record_id))

    db.delete(record)
    audit.append(db, actor, actor_role, "PatientRecordErased", record_id, "ok",
                 "Data klinis dan relasi off-chain dihapus; hash blockchain dipertahankan")


def orphaned_deleted_patient_ids(db: Session) -> list[str]:
    """Find records whose patient account was deleted and whose tombstone is in audit."""
    deleted_ids = db.scalars(
        select(AuditLog.record_id)
        .where(AuditLog.action == "UserDeleted", AuditLog.record_id.is_not(None))
        .distinct()
    ).all()
    result = []
    for record_id in deleted_ids:
        if db.get(Record, record_id) is None:
            continue
        owner = db.scalar(select(User.id).where(User.role == "pasien", User.patient_id == record_id))
        if owner is None:
            result.append(record_id)
    return result
