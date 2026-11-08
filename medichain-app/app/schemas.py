from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator


class LoginIn(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


class RegistrationStartIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=6, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=10, max_length=128)
    birth_date: date
    sex: Literal["L", "P"]
    address: str = Field(default="", max_length=1000)
    phone: str = Field(default="", max_length=30)


class PatientRegistrationIn(BaseModel):
    """Public sign-up creates only a pending patient account."""
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=2, max_length=120)
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str = Field(min_length=6, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=10, max_length=128)
    confirm_password: str = Field(min_length=10, max_length=128)
    birth_date: date
    sex: Literal["L", "P"]

    @field_validator("full_name")
    @classmethod
    def clean_full_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Nama lengkap minimal 2 karakter")
        return value

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @model_validator(mode="after")
    def validate_password_pair(self):
        if self.password != self.confirm_password:
            raise ValueError("Konfirmasi kata sandi tidak cocok")
        if (not any(c.islower() for c in self.password) or
                not any(c.isupper() for c in self.password) or
                not any(c.isdigit() for c in self.password)):
            raise ValueError("Kata sandi harus memuat huruf besar, huruf kecil, dan angka")
        return self


class RegistrationVerifyIn(BaseModel):
    challenge_id: str = Field(min_length=36, max_length=36)
    otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class GoogleCredentialIn(BaseModel):
    credential: str = Field(min_length=100, max_length=6000)


class PatientOnboardingIn(BaseModel):
    birth_date: date
    sex: Literal["L", "P"]
    address: str = Field(default="", max_length=1000)
    phone: str = Field(default="", max_length=30)


class AllergyIn(BaseModel):
    substance: str = Field(min_length=2, max_length=160)
    reaction: str = Field(default="", max_length=300)
    severity: Literal["unknown", "ringan", "sedang", "berat"] = "unknown"
    status: Literal["active", "resolved"] = "active"


class MedicationOrderIn(BaseModel):
    medication: str = Field(min_length=2, max_length=160)
    dose: str = Field(min_length=1, max_length=100)
    route: str = Field(default="Oral", min_length=2, max_length=60)
    frequency: str = Field(min_length=2, max_length=100)
    instructions: str = Field(default="", max_length=300)


class MedicationOrderUpdateIn(BaseModel):
    status: Literal["active", "discontinued", "completed"]


class DiagnosticOrderIn(BaseModel):
    kind: Literal["lab", "radiology"] = "lab"
    test_name: str = Field(min_length=2, max_length=160)
    clinical_note: str = Field(default="", max_length=300)


class DiagnosticOrderUpdateIn(BaseModel):
    status: Literal["requested", "collected", "completed", "cancelled"]
    result: str = Field(default="", max_length=4000)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class EcgIn(BaseModel):
    fs: int = Field(ge=100, le=1000)
    samples: List[float] = Field(min_length=100, max_length=20000)


class RecordIn(BaseModel):
    age: int = Field(ge=0, le=120)
    sex: Literal["L", "P"]
    history: str = Field(max_length=500)
    diagnosis: str = Field(min_length=1, max_length=1000)
    notes: str = Field(max_length=1000)
    ecg: EcgIn


class RecordUpdateIn(BaseModel):
    history: Optional[str] = Field(default=None, max_length=500)
    diagnosis: Optional[str] = Field(default=None, min_length=1, max_length=1000)
    notes: Optional[str] = Field(default=None, max_length=1000)


class AccessIn(BaseModel):
    allowed: bool


class TamperIn(BaseModel):
    target: Literal["diagnosis", "notes", "ecg"]


class UserCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "dokter", "pasien", "auditor"]
    specialty: Optional[Literal["Penyakit Dalam", "Jantung", "Bedah", "Saraf", "Ortopedi", "Anak", "Paru", "Kebidanan"]] = None
    full_name: str = Field(min_length=2, max_length=120)
    birth_date: Optional[date] = None
    sex: Optional[Literal["L", "P"]] = None
    address: str = Field(default="", max_length=1000)
    phone: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=254)


class UserUpdateIn(BaseModel):
    username: Optional[str] = Field(default=None, min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    specialty: Optional[Literal["Penyakit Dalam", "Jantung", "Bedah", "Saraf", "Ortopedi", "Anak", "Paru", "Kebidanan"]] = None
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    birth_date: Optional[date] = None
    sex: Optional[Literal["L", "P"]] = None
    address: Optional[str] = Field(default=None, max_length=1000)
    phone: Optional[str] = Field(default=None, max_length=30)
    email: Optional[str] = Field(default=None, max_length=254)
    role: Optional[Literal["admin", "dokter", "pasien", "auditor"]] = None
    is_active: Optional[bool] = None


class PasswordUpdateIn(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class ProfilePhotoIn(BaseModel):
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    data: str = Field(min_length=16, max_length=2_800_000)


class InvoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(min_length=1, max_length=36)
    description: str = Field(min_length=2, max_length=240)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    due_date: date


class InvoiceUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Optional[str] = Field(default=None, min_length=2, max_length=240)
    amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    due_date: Optional[date] = None


class InvoicePaymentProofIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    data: str = Field(min_length=16, max_length=2_800_000)


class InvoicePaymentProofReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reason: str = Field(default="", max_length=500)


class CareUpdateIn(BaseModel):
    status: Literal["dirawat", "operasi", "rawat_jalan", "pemulihan", "pulang"]
    room: str = Field(min_length=2, max_length=80)
    note: str = Field(default="", max_length=500)


class AppointmentIn(BaseModel):
    patient_id: str = Field(min_length=1, max_length=36)
    scheduled_at: datetime
    kind: str = Field(min_length=2, max_length=80)
    room: str = Field(default="Poli jantung", max_length=80)
    notes: str = Field(default="", max_length=500)


class AppointmentUpdateIn(BaseModel):
    scheduled_at: Optional[datetime] = None
    kind: Optional[str] = Field(default=None, min_length=2, max_length=80)
    room: Optional[str] = Field(default=None, max_length=80)
    notes: Optional[str] = Field(default=None, max_length=500)
    status: Optional[Literal["terjadwal", "selesai", "dibatalkan"]] = None


class AppointmentRequestIn(BaseModel):
    requested_at: datetime
    kind: str = Field(min_length=2, max_length=80)
    notes: str = Field(default="", max_length=500)


class AppointmentDecisionIn(BaseModel):
    decision: Literal["setujui", "tolak"]
    note: str = Field(default="", max_length=500)


class RecordShareIn(BaseModel):
    expires_minutes: int = Field(default=1440, ge=10, le=10080)
    scope: Literal["summary", "full"] = "summary"
    purpose: str = Field(default="", max_length=160)


class ShareAccessIn(BaseModel):
    token: str = Field(min_length=40, max_length=100)


class ClinicalObservationIn(BaseModel):
    heart_rate: Optional[int] = Field(default=None, ge=20, le=250)
    spo2: Optional[float] = Field(default=None, ge=50, le=100)
    temperature_c: Optional[float] = Field(default=None, ge=30, le=45)
    systolic_bp: Optional[int] = Field(default=None, ge=50, le=280)
    diastolic_bp: Optional[int] = Field(default=None, ge=30, le=180)
    note: str = Field(default="", max_length=300)
