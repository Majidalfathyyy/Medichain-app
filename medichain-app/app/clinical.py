"""Helpers for specialty-based inpatient assignment and patient timeline entries."""
from datetime import datetime
import hashlib

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import (CareEpisode, DoctorSpecialty, PatientActivity, PatientDoctorAssignment,
                 Record, User, UserProfile, PatientAllergy, MedicationOrder, DiagnosticOrder)
from .hashing import canonical_json, chain_key


SPECIALTIES = (
    "Penyakit Dalam", "Jantung", "Bedah", "Saraf", "Ortopedi", "Anak", "Paru", "Kebidanan",
)

_KEYWORDS = {
    "Jantung": ("jantung", "aritmi", "infark", "koroner", "angina", "gagal jantung"),
    "Bedah": ("apendis", "usus buntu", "hernia", "tumor", "bedah"),
    "Saraf": ("stroke", "kejang", "saraf", "epilepsi", "migrain"),
    "Ortopedi": ("fraktur", "patah tulang", "tulang", "sendi", "ortopedi"),
    "Anak": ("anak", "bayi", "pediatri"),
    "Paru": ("paru", "asma", "pneumonia", "tuberkulosis", "sesak"),
    "Kebidanan": ("hamil", "kehamilan", "persalinan", "kandungan"),
    "Penyakit Dalam": ("diabetes", "ginjal", "lambung", "hipertensi", "infeksi"),
}


def active_episode(db: Session, patient_id: str) -> CareEpisode | None:
    return db.scalar(select(CareEpisode).where(
        CareEpisode.patient_id == patient_id, CareEpisode.discharged_at.is_(None)
    ).order_by(CareEpisode.admitted_at.desc()))


def ecg_is_available(db: Session, patient_id: str, status: str | None = None) -> bool:
    episode = active_episode(db, patient_id)
    if status is None:
        from .db import PatientCare
        care = db.get(PatientCare, patient_id)
        status = care.status if care else "rawat_jalan"
    if status in ("dirawat", "operasi"):
        return True
    return status == "pemulihan" and bool(episode and episode.had_surgery)


def _doctor_name(db: Session, doctor: User) -> str:
    profile = db.get(UserProfile, doctor.id)
    return profile.full_name if profile else doctor.username


def choose_doctor(db: Session, diagnosis: str, history: str = "") -> tuple[User, str]:
    text = f"{diagnosis} {history}".casefold()
    desired = next((specialty for specialty, words in _KEYWORDS.items()
                    if any(word in text for word in words)), "Penyakit Dalam")
    candidates = list(db.scalars(
        select(User).join(DoctorSpecialty, DoctorSpecialty.user_id == User.id)
        .where(User.role == "dokter", User.is_active, DoctorSpecialty.specialty == desired)
        .order_by(User.id)
    ))
    specialty = desired
    fallback_any = False
    if not candidates and desired != "Penyakit Dalam":
        specialty = "Penyakit Dalam"
        candidates = list(db.scalars(
            select(User).join(DoctorSpecialty, DoctorSpecialty.user_id == User.id)
            .where(User.role == "dokter", User.is_active, DoctorSpecialty.specialty == specialty)
            .order_by(User.id)
        ))
    if not candidates:
        candidates = list(db.scalars(select(User).where(User.role == "dokter", User.is_active).order_by(User.id)))
        fallback_any = True
    if not candidates:
        raise HTTPException(409, "Belum ada dokter aktif untuk menangani rawat inap")
    loads = {
        doctor.id: db.scalar(select(func.count(CareEpisode.id)).where(
            CareEpisode.doctor_id == doctor.id, CareEpisode.discharged_at.is_(None)
        )) or 0
        for doctor in candidates
    }
    doctor = min(candidates, key=lambda item: (loads[item.id], item.id))
    if fallback_any:
        specialty_row = db.get(DoctorSpecialty, doctor.id)
        specialty = specialty_row.specialty if specialty_row else "Dokter Umum"
    return doctor, specialty


def ensure_patient_doctor_assignments(db: Session, assigned_by: str = "system") -> int:
    """Backfill existing records; records without an assignee stay inaccessible to doctors."""
    added = 0
    for rec in db.scalars(select(Record).order_by(Record.id)):
        assignment = db.get(PatientDoctorAssignment, rec.id)
        current_doctor = db.get(User, assignment.doctor_id) if assignment and assignment.doctor_id else None
        if current_doctor and current_doctor.role == "dokter" and current_doctor.is_active:
            continue
        try:
            doctor, specialty = choose_doctor(db, rec.diagnosis, rec.history)
        except HTTPException:
            break  # Staff accounts may be seeded after API startup.
        if assignment:
            assignment.doctor_id, assignment.specialty = doctor.id, specialty
            assignment.assigned_by = assigned_by
        else:
            db.add(PatientDoctorAssignment(patient_id=rec.id, doctor_id=doctor.id,
                                           specialty=specialty, assigned_by=assigned_by))
        episode = active_episode(db, rec.id)
        if episode:
            episode.doctor_id = doctor.id
            episode.doctor_name = _doctor_name(db, doctor)
            episode.specialty = specialty
        added += 1
    if added:
        db.flush()
    return added


def add_activity(db: Session, patient_id: str, activity_type: str, description: str,
                 actor: str, episode: CareEpisode | None = None, doctor: User | None = None,
                 specialty: str = "") -> PatientActivity:
    if doctor is None and episode and episode.doctor_id:
        doctor = db.get(User, episode.doctor_id)
    profile_name = _doctor_name(db, doctor) if doctor else (episode.doctor_name if episode else "")
    event = PatientActivity(
        patient_id=patient_id,
        episode_id=episode.id if episode else None,
        activity_type=activity_type,
        description=description[:500],
        actor=actor[:40],
        doctor_id=doctor.id if doctor else (episode.doctor_id if episode else None),
        doctor_name=profile_name,
        specialty=specialty or (episode.specialty if episode else ""),
        occurred_at=datetime.utcnow(),
    )
    db.add(event)
    db.flush()
    _, timeline_hash = timeline_snapshot(db, patient_id)
    from .chain_ops import enqueue_timeline_anchor
    actor_user = db.scalar(select(User).where(User.username == actor))
    enqueue_timeline_anchor(db, patient_id, chain_key(patient_id), timeline_hash,
                            actor, actor_user.role if actor_user else None)
    return event


def timeline_snapshot(db: Session, patient_id: str) -> tuple[list[dict], str]:
    events = list(db.scalars(select(PatientActivity).where(
        PatientActivity.patient_id == patient_id
    ).order_by(PatientActivity.id)))
    payload = [{"id": item.id, "episode_id": item.episode_id, "type": item.activity_type,
                "description": item.description, "actor": item.actor,
                "doctor_name": item.doctor_name, "specialty": item.specialty,
                "occurred_at": item.occurred_at.isoformat()} for item in events]
    rec = db.get(Record, patient_id)
    salt = bytes.fromhex(rec.salt) if rec and rec.salt else b""
    clinical_state = {
        "allergies": [{"id": x.id, "substance": x.substance, "reaction": x.reaction,
                       "severity": x.severity, "status": x.status, "recorded_by": x.recorded_by,
                       "created_at": x.created_at.isoformat()} for x in db.scalars(
                           select(PatientAllergy).where(PatientAllergy.patient_id == patient_id).order_by(PatientAllergy.id))],
        "medications": [{"id": x.id, "medication": x.medication, "dose": x.dose, "route": x.route,
                         "frequency": x.frequency, "instructions": x.instructions, "status": x.status,
                         "prescribed_by": x.prescribed_by, "start_at": x.start_at.isoformat(),
                         "end_at": x.end_at.isoformat() if x.end_at else None} for x in db.scalars(
                             select(MedicationOrder).where(MedicationOrder.patient_id == patient_id).order_by(MedicationOrder.id))],
        "diagnostics": [{"id": x.id, "kind": x.kind, "test_name": x.test_name,
                         "clinical_note": x.clinical_note, "status": x.status, "result": x.result,
                         "ordered_by": x.ordered_by, "ordered_at": x.ordered_at.isoformat(),
                         "resulted_at": x.resulted_at.isoformat() if x.resulted_at else None} for x in db.scalars(
                             select(DiagnosticOrder).where(DiagnosticOrder.patient_id == patient_id).order_by(DiagnosticOrder.id))],
    }
    # Preserve legacy fingerprints for patients without these newer chart sections.
    snapshot = {"events": payload, "clinical": clinical_state} if any(clinical_state.values()) else payload
    digest = hashlib.sha256(salt + canonical_json(snapshot)).hexdigest()
    return payload, digest


def start_episode(db: Session, patient_id: str, diagnosis: str, history: str,
                  actor: str, status: str) -> CareEpisode:
    existing = active_episode(db, patient_id)
    if existing:
        episode = existing
        doctor = db.get(User, episode.doctor_id) if episode.doctor_id else None
    else:
        doctor, specialty = choose_doctor(db, diagnosis, history)
        episode = CareEpisode(
            patient_id=patient_id,
            doctor_id=doctor.id,
            doctor_name=_doctor_name(db, doctor),
            specialty=specialty,
            admission_reason=(diagnosis or history or "Rawat inap")[:500],
            had_surgery=status == "operasi",
        )
        db.add(episode)
        db.flush()
        add_activity(db, patient_id, "masuk", f"Pasien masuk rawat inap. Dokter penanggung jawab: {episode.doctor_name} ({specialty}).",
                     actor, episode, doctor, specialty)
        if status == "operasi":
            add_activity(db, patient_id, "operasi", "Pasien menjalani operasi.", actor, episode, doctor)
    if status == "operasi" and not episode.had_surgery:
        episode.had_surgery = True
        add_activity(db, patient_id, "operasi", "Pasien menjalani operasi.", actor, episode, doctor)
    return episode
