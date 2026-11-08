from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings

_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=_args)
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Record(Base):
    """Rekam medis sintetis (off-chain). Hanya pengenal pseudonim, tanpa data pribadi nyata."""
    __tablename__ = "records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pseudo_id: Mapped[str] = mapped_column(String(16), unique=True)
    age: Mapped[int] = mapped_column(Integer)
    sex: Mapped[str] = mapped_column(String(1))
    history: Mapped[str] = mapped_column(Text)
    diagnosis: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text)
    salt: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1)


class PatientProfile(Base):
    """Identitas pasien off-chain, terpisah dari rekam klinis dan akun login."""
    __tablename__ = "patient_profiles"
    record_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    sex: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(254), default="")


class Biosignal(Base):
    __tablename__ = "biosignals"
    record_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), primary_key=True)
    fs: Mapped[int] = mapped_column(Integer)
    samples: Mapped[str] = mapped_column(Text)  # JSON list float
    salt: Mapped[str] = mapped_column(String(32))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(10))
    patient_id: Mapped[Optional[str]] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[float] = mapped_column(Float, default=0)


class UserProfile(Base):
    """Informasi pribadi yang hanya disimpan off-chain."""
    __tablename__ = "user_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    sex: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(254), default="")


class AuthIdentity(Base):
    __tablename__ = "auth_identities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(24))
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_auth_identity_provider_subject"),)


class EmailOtpChallenge(Base):
    __tablename__ = "email_otp_challenges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    username: Mapped[str] = mapped_column(String(40))
    password_hash: Mapped[str] = mapped_column(String(200))
    full_name: Mapped[str] = mapped_column(String(120))
    birth_date: Mapped[date] = mapped_column(Date)
    sex: Mapped[str] = mapped_column(String(1))
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    otp_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PatientAllergy(Base):
    __tablename__ = "patient_allergies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    substance: Mapped[str] = mapped_column(String(160))
    reaction: Mapped[str] = mapped_column(String(300), default="")
    severity: Mapped[str] = mapped_column(String(16), default="unknown")
    status: Mapped[str] = mapped_column(String(16), default="active")
    recorded_by: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MedicationOrder(Base):
    __tablename__ = "medication_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    medication: Mapped[str] = mapped_column(String(160))
    dose: Mapped[str] = mapped_column(String(100))
    route: Mapped[str] = mapped_column(String(60), default="Oral")
    frequency: Mapped[str] = mapped_column(String(100))
    instructions: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")
    prescribed_by: Mapped[str] = mapped_column(String(40))
    start_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    end_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DiagnosticOrder(Base):
    __tablename__ = "diagnostic_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="lab")
    test_name: Mapped[str] = mapped_column(String(160))
    clinical_note: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(16), default="requested")
    result: Mapped[str] = mapped_column(Text, default="")
    ordered_by: Mapped[str] = mapped_column(String(40))
    ordered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resulted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ProfilePhoto(Base):
    """Foto profil akun disimpan privat di database, terpisah dari rekam medis."""
    __tablename__ = "profile_photos"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    content_type: Mapped[str] = mapped_column(String(32))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(String(240))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    due_date: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(16), default="belum_lunas")
    created_by: Mapped[str] = mapped_column(String(40))


class InvoicePaymentProof(Base):
    """Patient-uploaded payment evidence awaiting an explicit admin decision."""
    __tablename__ = "invoice_payment_proofs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    submitted_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    content_type: Mapped[str] = mapped_column(String(32))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    rejection_reason: Mapped[str] = mapped_column(String(500), default="")
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class PatientCare(Base):
    """Status perawatan aktif yang dapat dibaca pasien dan petugas berizin."""
    __tablename__ = "patient_care"
    patient_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="rawat_jalan")
    room: Mapped[str] = mapped_column(String(80), default="Belum ditentukan")
    note: Mapped[str] = mapped_column(String(500), default="")
    updated_by: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DoctorSpecialty(Base):
    __tablename__ = "doctor_specialties"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    specialty: Mapped[str] = mapped_column(String(60), index=True)


class PatientDoctorAssignment(Base):
    """Dokter penanggung jawab untuk akses klinis pasien rawat jalan maupun inap."""
    __tablename__ = "patient_doctor_assignments"
    patient_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), primary_key=True)
    doctor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    specialty: Mapped[str] = mapped_column(String(60), default="")
    assigned_by: Mapped[str] = mapped_column(String(40), default="system")
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CareEpisode(Base):
    __tablename__ = "care_episodes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    doctor_name: Mapped[str] = mapped_column(String(120), default="")
    specialty: Mapped[str] = mapped_column(String(60))
    admitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    discharged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    had_surgery: Mapped[bool] = mapped_column(Boolean, default=False)
    admission_reason: Mapped[str] = mapped_column(String(500), default="")


class PatientActivity(Base):
    __tablename__ = "patient_activities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("care_episodes.id", ondelete="SET NULL"), nullable=True)
    activity_type: Mapped[str] = mapped_column(String(40), index=True)
    description: Mapped[str] = mapped_column(String(500))
    actor: Mapped[str] = mapped_column(String(40))
    doctor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    doctor_name: Mapped[str] = mapped_column(String(120), default="")
    specialty: Mapped[str] = mapped_column(String(60), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ClinicalObservation(Base):
    """Structured demo vitals entered by a clinician; alerts are review prompts only."""
    __tablename__ = "clinical_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    observed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    heart_rate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    spo2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    temperature_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    systolic_bp: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    diastolic_bp: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class RecordShare(Base):
    """Patient-approved bearer link. Only a SHA-256 token digest is stored."""
    __tablename__ = "record_shares"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(12), default="summary")
    purpose: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class RecordShareAccess(Base):
    __tablename__ = "record_share_accesses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    share_id: Mapped[str] = mapped_column(ForeignKey("record_shares.id", ondelete="CASCADE"), index=True)
    accessed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    outcome: Mapped[str] = mapped_column(String(20), default="opened")


class TimelineAnchor(Base):
    """Snapshot digest of care events, queued for an AccessLogged chain event."""
    __tablename__ = "timeline_anchors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    timeline_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    tx_hash: Mapped[Optional[str]] = mapped_column(String(66), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    kind: Mapped[str] = mapped_column(String(80), default="Kontrol")
    room: Mapped[str] = mapped_column(String(80), default="Poli jantung")
    notes: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(20), default="terjadwal")
    created_by: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AppointmentRequest(Base):
    __tablename__ = "appointment_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    kind: Mapped[str] = mapped_column(String(80), default="Pemeriksaan")
    notes: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(24), default="menunggu_dokter")
    doctor_approved_by: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    admin_approved_by: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    decision_note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Access(Base):
    """Cermin izin on-chain (grantAccess/revokeAccess) per rekam dan peran."""
    __tablename__ = "access"
    record_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(10), primary_key=True)
    allowed: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(25))
    actor: Mapped[str] = mapped_column(String(40))
    role: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    record_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    outcome: Mapped[str] = mapped_column(String(10))
    detail: Mapped[str] = mapped_column(Text, default="")
    tx_hash: Mapped[Optional[str]] = mapped_column(String(66), nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class ChainOperation(Base):
    """Durable outbox for chain writes that cannot share a DB transaction."""
    __tablename__ = "chain_operations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation: Mapped[str] = mapped_column(String(12))
    record_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    record_key: Mapped[str] = mapped_column(String(64), index=True)
    hash_record: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    hash_ecg: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    role_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    allowed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    expected_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    actor: Mapped[str] = mapped_column(String(40))
    actor_role: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    tx_hash: Mapped[Optional[str]] = mapped_column(String(66), nullable=True)
    last_error: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def init_db() -> None:
    """Dev/tes. Di production gunakan migrasi (Alembic)."""
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
