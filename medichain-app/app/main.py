import base64
import binascii
import hashlib
import json
import secrets
import smtplib
import time
import uuid
import hmac
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path
from contextlib import asynccontextmanager

from datetime import date, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import jwt as pyjwt

from . import audit, services
from .chain_ops import enqueue_access, enqueue_record_update, enqueue_timeline_anchor, process_pending
from .chain import ChainClient, chain_metadata, get_chain
from .clinical import (active_episode, add_activity, choose_doctor, ecg_is_available,
                       ensure_patient_doctor_assignments, start_episode, timeline_snapshot)
from .config import settings
from .db import (Access, Appointment, AppointmentRequest, AuditLog, Biosignal, ChainOperation, DoctorSpecialty, Invoice,
                 InvoicePaymentProof, PatientActivity, PatientCare, PatientDoctorAssignment, PatientProfile, Record, SessionLocal,
                 ProfilePhoto, RecordShare, RecordShareAccess, ClinicalObservation, TimelineAnchor,
                 User, UserProfile, AuthIdentity, EmailOtpChallenge, PatientAllergy, MedicationOrder,
                 DiagnosticOrder, get_db, init_db)
from .hashing import canonical_json, chain_key, role_hash
from .retention import erase_patient_record
from .schemas import (AccessIn, AppointmentDecisionIn, AppointmentIn, AppointmentRequestIn,
                      AppointmentUpdateIn, CareUpdateIn, ClinicalObservationIn, InvoiceIn, InvoiceUpdateIn, LoginIn,
                      RegistrationStartIn, RegistrationVerifyIn, GoogleCredentialIn, PatientOnboardingIn,
                      AllergyIn, MedicationOrderIn, MedicationOrderUpdateIn, DiagnosticOrderIn, DiagnosticOrderUpdateIn,
                      PasswordUpdateIn, ProfilePhotoIn, RecordIn, RecordShareIn, RecordUpdateIn, ShareAccessIn,
                      PatientRegistrationIn, TamperIn, TokenOut,
                      InvoicePaymentProofIn, InvoicePaymentProofReviewIn, UserCreateIn, UserUpdateIn)
from .security import ACL_ROLES, DUMMY_HASH, RateLimiter, create_token, decode_token, hash_password, verify_password

MAX_FAILED, LOCK_SECONDS = 5, 15 * 60
API_CSP = "default-src 'none'; frame-ancestors 'none'"
WEB_CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
           "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
FRONT = Path(__file__).resolve().parent.parent / "frontend"
login_limiter = RateLimiter(10, 60)       # 10 percobaan login / menit / (ip, username)
deny_chain_limiter = RateLimiter(1, 60)   # 1 log on-chain penolakan / menit / (user, rekam): cegah pengurasan gas
share_limiter = RateLimiter(30, 60)
registration_limiter = RateLimiter(4, 900)
public_registration_limiter = RateLimiter(4, 900)
google_limiter = RateLimiter(10, 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Development/tests may create their schema automatically. Production
    # schema changes are applied explicitly through Alembic before Uvicorn.
    if not settings.is_prod:
        init_db()
    with SessionLocal() as db:
        ensure_patient_doctor_assignments(db)
        db.commit()
        process_pending(db, get_chain())
    yield


app = FastAPI(title="MediChain API", version="0.1.0", lifespan=lifespan,
              docs_url=None if settings.is_prod else "/docs", redoc_url=None,
              openapi_url=None if settings.is_prod else "/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method == "POST" and request.url.path == "/auth/register":
        ip = request.client.host if request.client else "?"
        if not public_registration_limiter.allow(ip):
            resp = JSONResponse(status_code=429, content={"detail": "Terlalu banyak percobaan pendaftaran. Coba lagi nanti."})
        else:
            resp = await call_next(request)
    else:
        resp = await call_next(request)
    resp.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                         "Cache-Control": "no-store"})
    path = request.url.path
    if path.startswith("/app"):
        resp.headers["Content-Security-Policy"] = WEB_CSP
    elif path not in ("/docs", "/openapi.json"):  # Swagger UI (hanya dev) butuh skrip CDN
        resp.headers["Content-Security-Policy"] = API_CSP
    if settings.is_prod:
        resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return resp


@app.exception_handler(RequestValidationError)
async def safe_validation_error(_: Request, exc: RequestValidationError):
    # Validation responses must not echo submitted passwords or other private fields.
    details = [{"loc": error.get("loc", []), "msg": error.get("msg", "Input tidak valid"),
                "type": error.get("type", "value_error")} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": details})


# ---------- autentikasi dan otorisasi ----------
bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)) -> User:
    unauth = HTTPException(401, "Autentikasi diperlukan", headers={"WWW-Authenticate": "Bearer"})
    if not creds:
        raise unauth
    try:
        claims = decode_token(creds.credentials)
        user = db.get(User, int(claims["sub"]))
    except (pyjwt.PyJWTError, ValueError):
        raise unauth
    if not user or not user.is_active:
        raise unauth
    return user  # peran dari DB, bukan dari token


def require_role(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Peran tidak diizinkan")
        return user
    return dep


def _record(db: Session, rid: str) -> Record:
    rec = db.get(Record, rid)
    if not rec:
        raise HTTPException(404, "Rekam tidak ditemukan")
    return rec


def _record_for_update(db: Session, rid: str) -> Record:
    rec = db.scalar(select(Record).where(Record.id == rid).with_for_update())
    if not rec:
        raise HTTPException(404, "Rekam tidak ditemukan")
    return rec


def _integrity_result(db: Session, chain: ChainClient, rec: Record) -> dict:
    pending = db.scalar(select(ChainOperation.id).where(
        ChainOperation.record_id == rec.id, ChainOperation.operation.in_(("register", "update")),
        ChainOperation.status == "pending").limit(1)) is not None
    try:
        result = services.check_integrity(db, chain, rec)
    except Exception:
        if not pending:
            raise
        hr, he = services.local_hashes(db, rec)
        result = {"status": "sync_pending", "record_ok": False, "ecg_ok": False,
                  "local": {"hash_record": hr, "hash_ecg": he}, "onchain": None}
    if pending and result["status"] != "valid":
        result["status"] = "sync_pending"
    info = chain_metadata()
    tx_hash = db.scalar(
        select(AuditLog.tx_hash)
        .where(AuditLog.record_id == rec.id,
               AuditLog.action.in_(("RecordRegisteredOnChain", "RecordUpdatedOnChain")),
               AuditLog.tx_hash.is_not(None))
        .order_by(AuditLog.id.desc()).limit(1)
    )
    result.update({"chain": {"mode": info["mode"], "network": info["network"], "chain_id": info["chain_id"]},
                   "transaction_hash": tx_hash,
                   "explorer_tx_url": f"{info['explorer_tx_base']}{tx_hash}" if tx_hash and info["explorer_tx_base"] else None,
                   "chain_sync_pending": pending})
    return result


def _pending_chain_count(db: Session, record_id: str | None = None) -> int:
    query = select(func.count()).select_from(ChainOperation).where(ChainOperation.status == "pending")
    if record_id:
        query = query.where(ChainOperation.record_id == record_id)
    return int(db.scalar(query) or 0)


def _fhir_bundle(db: Session, chain: ChainClient, rec: Record, scope: str = "summary") -> dict:
    profile = db.get(PatientProfile, rec.id)
    care = db.get(PatientCare, rec.id)
    episode = active_episode(db, rec.id)
    gender = {"L": "male", "P": "female"}.get(rec.sex, "unknown")
    patient = {"resourceType": "Patient", "id": rec.pseudo_id,
               "identifier": [{"system": "https://medichain.local/patient-id", "value": rec.pseudo_id}],
               "name": [{"text": profile.full_name if profile else "Nama belum diisi"}], "gender": gender}
    if profile and profile.birth_date:
        patient["birthDate"] = profile.birth_date.isoformat()
    if profile and profile.address:
        patient["address"] = [{"text": profile.address}]
    if profile and (profile.phone or profile.email):
        patient["telecom"] = ([{"system": "phone", "value": profile.phone}] if profile.phone else []) + ([{"system": "email", "value": profile.email}] if profile.email else [])

    status = care.status if care else "rawat_jalan"
    encounter_status = "in-progress" if status in ("dirawat", "operasi") else "finished" if status in ("pulang", "pemulihan") else "planned"
    encounter_class = "IMP" if status in ("dirawat", "operasi", "pemulihan") else "AMB"
    encounter = {"resourceType": "Encounter", "id": f"enc-{rec.pseudo_id.lower()}", "status": encounter_status,
                 "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": encounter_class},
                 "subject": {"reference": f"Patient/{rec.pseudo_id}"},
                 "reasonCode": [{"text": (episode.admission_reason if episode else rec.diagnosis) or "Pemeriksaan"}]}
    if care and care.room and care.room != "Belum ditentukan":
        encounter["location"] = [{"location": {"display": care.room}, "status": "active" if encounter_status == "in-progress" else "completed"}]
    entries = [{"resource": patient}, {"resource": encounter}]
    condition = {"resourceType": "Condition", "id": f"condition-{rec.pseudo_id.lower()}",
                 "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
                 "code": {"text": rec.diagnosis}, "subject": {"reference": f"Patient/{rec.pseudo_id}"},
                 "encounter": {"reference": f"Encounter/{encounter['id']}"}}
    entries.append({"resource": condition})

    if scope == "full":
        if rec.history:
            entries.append({"resource": {"resourceType": "Condition", "id": f"history-{rec.pseudo_id.lower()}",
                            "code": {"text": rec.history}, "subject": {"reference": f"Patient/{rec.pseudo_id}"}, "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "unconfirmed"}]}}})
        if rec.notes:
            data = base64.b64encode(rec.notes.encode("utf-8")).decode("ascii")
            entries.append({"resource": {"resourceType": "DocumentReference", "id": f"notes-{rec.pseudo_id.lower()}",
                            "status": "current", "subject": {"reference": f"Patient/{rec.pseudo_id}"},
                            "content": [{"attachment": {"contentType": "text/plain; charset=utf-8", "data": data}}]}})
        observations = list(db.scalars(select(ClinicalObservation).where(
            ClinicalObservation.patient_id == rec.id
        ).order_by(ClinicalObservation.observed_at.desc()).limit(50)))
        for observation in observations:
            components = []
            for value, code, display, unit, system in (
                (observation.heart_rate, "8867-4", "Heart rate", "/min", "http://unitsofmeasure.org"),
                (observation.spo2, "59408-5", "Oxygen saturation", "%", "http://unitsofmeasure.org"),
                (observation.temperature_c, "8310-5", "Body temperature", "Cel", "http://unitsofmeasure.org"),
            ):
                if value is not None:
                    components.append({"code": {"coding": [{"system": "http://loinc.org", "code": code, "display": display}]}, "valueQuantity": {"value": value, "unit": unit, "system": system, "code": unit}})
            if observation.systolic_bp is not None or observation.diastolic_bp is not None:
                bp_components = []
                if observation.systolic_bp is not None:
                    bp_components.append({"code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"}]}, "valueQuantity": {"value": observation.systolic_bp, "unit": "mm[Hg]", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}})
                if observation.diastolic_bp is not None:
                    bp_components.append({"code": {"coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic blood pressure"}]}, "valueQuantity": {"value": observation.diastolic_bp, "unit": "mm[Hg]", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}})
                components.extend(bp_components)
            entries.append({"resource": {"resourceType": "Observation", "id": f"vitals-{observation.id}", "status": "final",
                            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
                            "code": {"text": "Vital signs"}, "subject": {"reference": f"Patient/{rec.pseudo_id}"},
                            "effectiveDateTime": observation.observed_at.isoformat() + "Z", "component": components}})
        for allergy in db.scalars(select(PatientAllergy).where(PatientAllergy.patient_id == rec.id)):
            entries.append({"resource": {"resourceType": "AllergyIntolerance", "id": f"allergy-{allergy.id}",
                            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active" if allergy.status == "active" else "resolved"}]},
                            "code": {"text": allergy.substance}, "patient": {"reference": f"Patient/{rec.pseudo_id}"},
                            "reaction": ([{"manifestation": [{"text": allergy.reaction}],
                                           **({"severity": {"ringan": "mild", "sedang": "moderate", "berat": "severe"}[allergy.severity]}
                                              if allergy.severity in ("ringan", "sedang", "berat") else {})}]
                                         if allergy.reaction else [])}})
        for medication in db.scalars(select(MedicationOrder).where(MedicationOrder.patient_id == rec.id)):
            entries.append({"resource": {"resourceType": "MedicationRequest", "id": f"medication-{medication.id}",
                            "status": medication.status if medication.status in ("active", "completed") else "stopped",
                            "intent": "order", "medicationCodeableConcept": {"text": medication.medication},
                            "subject": {"reference": f"Patient/{rec.pseudo_id}"},
                            "dosageInstruction": [{"text": f"{medication.dose}; {medication.route}; {medication.frequency}" + (f"; {medication.instructions}" if medication.instructions else "")}]}})
        for diagnostic in db.scalars(select(DiagnosticOrder).where(DiagnosticOrder.patient_id == rec.id)):
            status_map = {"requested": "active", "collected": "active", "completed": "completed", "cancelled": "revoked"}
            entries.append({"resource": {"resourceType": "ServiceRequest", "id": f"diagnostic-{diagnostic.id}",
                            "status": status_map[diagnostic.status], "intent": "order",
                            "category": [{"text": "Laboratory" if diagnostic.kind == "lab" else "Radiology"}],
                            "code": {"text": diagnostic.test_name}, "subject": {"reference": f"Patient/{rec.pseudo_id}"},
                            "note": ([{"text": diagnostic.clinical_note}] if diagnostic.clinical_note else [])}})
        timeline_events, timeline_digest = timeline_snapshot(db, rec.id)
        for event in timeline_events:
            entries.append({"resource": {"resourceType": "Provenance", "id": f"timeline-{event['id']}",
                            "target": [{"reference": f"Encounter/{encounter['id']}"}],
                            "recorded": event["occurred_at"] + "Z",
                            "activity": {"text": f"{event['type']}: {event['description']}"},
                            "agent": [{"who": {"display": event["actor"]}}]}})
    else:
        _, timeline_digest = timeline_snapshot(db, rec.id)
    timeline_anchor = db.scalar(select(TimelineAnchor).where(
        TimelineAnchor.patient_id == rec.id, TimelineAnchor.timeline_hash == timeline_digest,
        TimelineAnchor.status == "confirmed"
    ).order_by(TimelineAnchor.id.desc()).limit(1))
    timeline_pending = db.scalar(select(TimelineAnchor).where(
        TimelineAnchor.patient_id == rec.id, TimelineAnchor.timeline_hash == timeline_digest,
        TimelineAnchor.status == "pending"
    ).order_by(TimelineAnchor.id.desc()).limit(1))
    timeline_anchor_status = "confirmed" if timeline_anchor else "pending" if timeline_pending else "unanchored"

    bundle_entries = []
    for entry in entries:
        resource = entry["resource"]
        stable_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"{resource['resourceType']}/{resource['id']}")
        bundle_entries.append({"fullUrl": f"urn:uuid:{stable_uuid}", **entry})
    bundle = {"resourceType": "Bundle", "meta": {"profile": ["http://hl7.org/fhir/StructureDefinition/Bundle|4.0.1"]},
              "type": "collection", "timestamp": datetime.utcnow().isoformat() + "Z",
              "entry": bundle_entries}
    export_fingerprint = hashlib.sha256(canonical_json({"resourceType": "Bundle", "meta": bundle["meta"],
                                                        "type": "collection", "entry": bundle_entries})).hexdigest()
    try:
        integrity = services.check_integrity(db, chain, rec)
    except Exception:
        integrity = {"status": "unavailable", "onchain": None}
    chain_info = chain_metadata()
    bundle["extension"] = [{"url": "https://medichain.local/fhir/StructureDefinition/integrity-proof", "extension": [
        {"url": "sourceStatus", "valueCode": integrity["status"]},
        {"url": "sourceRecordVersion", "valueInteger": rec.version},
        {"url": "chainNetwork", "valueString": chain_info["network"]},
        {"url": "exportFingerprint", "valueString": export_fingerprint},
        *([{"url": "timelineFingerprint", "valueString": timeline_digest},
           {"url": "timelineAnchorStatus", "valueCode": timeline_anchor_status},
           *([{"url": "timelineTransactionHash", "valueString": timeline_anchor.tx_hash}] if timeline_anchor and timeline_anchor.tx_hash else [])]
          if scope == "full" else []),
    ]}]
    return {"bundle": bundle, "integrity": {"status": integrity["status"], "export_fingerprint": export_fingerprint,
            "source_record_version": rec.version, "chain_network": chain_info["network"],
            "chain_version": integrity.get("onchain", {}).get("version") if integrity.get("onchain") else None,
            "timeline_anchor_status": timeline_anchor_status,
            "timeline_transaction_hash": timeline_anchor.tx_hash if timeline_anchor else None}}


def _allowed(db: Session, user: User, rec: Record, action: str) -> bool:
    row = db.get(Access, (rec.id, user.role))
    if action == "write":
        return user.role == "dokter" and bool(row and row.allowed)
    if user.role == "admin":
        return True
    if user.role == "dokter":
        episode = active_episode(db, rec.id)
        assignment = db.get(PatientDoctorAssignment, rec.id)
        assigned_doctor_id = episode.doctor_id if episode and episode.doctor_id else (assignment.doctor_id if assignment else None)
        if assigned_doctor_id != user.id:
            return False
    if user.role == "pasien" and user.patient_id != rec.id:
        return False
    return bool(row and row.allowed)


def _guard(db: Session, chain: ChainClient, user: User, rec: Record, action: str) -> None:
    if _allowed(db, user, rec, action):
        return
    tx = None
    if deny_chain_limiter.allow(f"{user.id}:{rec.id}"):
        try:
            tx = chain.log_access(chain_key(rec.id), "denied:" + action).tx_hash
        except Exception:
            pass  # kegagalan chain tidak boleh menyembunyikan penolakan
    audit.append(db, user.username, user.role, "AccessLogged", rec.id, "denied", f"{action} ditolak", tx)
    db.commit()
    raise HTTPException(403, "Akses ditolak")


@app.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "?"
    if not login_limiter.allow(f"{ip}:{body.username}"):
        raise HTTPException(429, "Terlalu banyak percobaan, coba lagi nanti")
    user = db.scalar(select(User).where(User.username == body.username))
    now = time.time()
    locked = bool(user and user.locked_until > now)
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)  # waktu seragam
    if user and ok and not locked and not user.is_active and user.role == "pasien" and not user.patient_id:
        audit.append(db, user.username, user.role, "LOGIN_PENDING_APPROVAL", None, "denied",
                     "akun pasien menunggu persetujuan")
        db.commit()
        raise HTTPException(403, "Akun menunggu persetujuan admin atau auditor.")
    if not (user and ok and not locked and user.is_active):
        if user and not locked:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED:
                user.locked_until, user.failed_logins = now + LOCK_SECONDS, 0
        audit.append(db, body.username, None, "LOGIN", None, "denied", "terkunci" if locked else "kredensial salah")
        db.commit()
        raise HTTPException(401, "Username atau password salah")  # pesan sama untuk semua kasus
    user.failed_logins = 0
    audit.append(db, user.username, user.role, "LOGIN", None, "ok")
    db.commit()
    return TokenOut(access_token=create_token(user.id), role=user.role)


def _send_registration_otp(email: str, code: str) -> None:
    if not (settings.smtp_host and settings.smtp_from):
        raise HTTPException(503, "Pendaftaran email belum dikonfigurasi. Minta administrator mengatur SMTP.")
    message = EmailMessage()
    message["Subject"] = "Kode verifikasi MediChain"
    message["From"] = settings.smtp_from
    message["To"] = email
    message.set_content(f"Kode verifikasi Anda: {code}\n\nKode berlaku selama 10 menit. Jangan bagikan kode ini kepada siapa pun.")
    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=12) as server:
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=12) as server:
                server.ehlo()
                if settings.smtp_use_tls:
                    server.starttls()
                    server.ehlo()
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(503, "Email verifikasi gagal dikirim. Periksa konfigurasi layanan email.") from exc


def _otp_digest(challenge_id: str, email: str, otp: str) -> str:
    return hmac.new(settings.otp_secret.encode(), f"{challenge_id}:{email}:{otp}".encode(), hashlib.sha256).hexdigest()


def _username_for(db: Session, full_name: str, email: str) -> str:
    import re
    base = re.sub(r"[^a-z0-9]+", ".", (email.split("@", 1)[0] or full_name).casefold()).strip(".")[:30] or "pasien"
    candidate = base
    while db.scalar(select(User.id).where(User.username == candidate)):
        candidate = f"{base[:25]}.{secrets.token_hex(2)}"
    return candidate


def _create_self_service_patient(db: Session, chain: ChainClient, *, full_name: str, email: str,
                                 password_hash: str, birth_date: date, sex: str,
                                 address: str = "", phone: str = "") -> User:
    if db.scalar(select(User.id).join(UserProfile, UserProfile.user_id == User.id).where(func.lower(UserProfile.email) == email.lower())):
        raise HTTPException(409, "Email sudah terdaftar. Silakan masuk atau gunakan email lain.")
    if birth_date > date.today():
        raise HTTPException(422, "Tanggal lahir tidak boleh di masa depan")
    age = date.today().year - birth_date.year - ((date.today().month, date.today().day) < (birth_date.month, birth_date.day))
    if age > 120:
        raise HTTPException(422, "Tanggal lahir tidak valid")
    account = User(username=_username_for(db, full_name, email), password_hash=password_hash, role="pasien")
    db.add(account)
    db.flush()
    profile = UserProfile(user_id=account.id, full_name=full_name.strip(), birth_date=birth_date,
                          sex=sex, address=address.strip(), phone=phone.strip(), email=email.lower())
    db.add(profile)
    _attach_patient_record(db, chain, account, profile, birth_date, sex, address, phone)
    return account


def _attach_patient_record(db: Session, chain: ChainClient, account: User, profile: UserProfile,
                           birth_date: date, sex: str, address: str = "", phone: str = "",
                           audit_registration: bool = True) -> Record:
    if birth_date > date.today():
        raise HTTPException(422, "Tanggal lahir tidak boleh di masa depan")
    age = date.today().year - birth_date.year - ((date.today().month, date.today().day) < (birth_date.month, birth_date.day))
    if age > 120:
        raise HTTPException(422, "Tanggal lahir tidak valid")
    data = RecordIn(age=age, sex=sex, history="Profil pasien baru", diagnosis="Belum ada diagnosis",
                    notes="Rekam medis awal dibuat setelah pendaftaran pasien diselesaikan.",
                    ecg={"fs": 250, "samples": services.make_patient_ecg(account.id * 7919)})
    rec = services.create_record(db, chain, account, data)
    account.patient_id = rec.id
    db.add(PatientProfile(record_id=rec.id, full_name=profile.full_name, birth_date=birth_date,
                          sex=sex, address=address.strip(), phone=phone.strip(), email=profile.email.lower()))
    patient_access = db.get(Access, (rec.id, "pasien"))
    if patient_access:
        patient_access.allowed = True
    try:
        doctor, specialty = choose_doctor(db, data.diagnosis, data.history)
        db.add(PatientDoctorAssignment(patient_id=rec.id, doctor_id=doctor.id, specialty=specialty,
                                       assigned_by="system-registration"))
    except HTTPException:
        # Registrasi tetap dapat dilanjutkan; petugas dapat mengalokasikan dokter kemudian.
        pass
    enqueue_access(db, rec.id, chain_key(rec.id), role_hash("pasien"), True, account.username, account.role)
    add_activity(db, rec.id, "registrasi", "Rekam medis awal pasien dibuat.", account.username)
    if audit_registration:
        audit.append(db, account.username, account.role, "SELF_REGISTRATION", rec.id, "pending",
                     "Pendaftaran pasien selesai")
    return rec


def _email_owner(db: Session, email: str, exclude_user_id: int | None = None) -> int | None:
    query = select(UserProfile.user_id).where(func.lower(UserProfile.email) == email.strip().lower(),
                                               UserProfile.email != "")
    if exclude_user_id is not None:
        query = query.where(UserProfile.user_id != exclude_user_id)
    return db.scalar(query.limit(1))


@app.post("/auth/register", status_code=202)
def register_patient(body: PatientRegistrationIn, db: Session = Depends(get_db)):
    if body.birth_date > date.today():
        raise HTTPException(422, "Tanggal lahir tidak boleh di masa depan.")
    age = date.today().year - body.birth_date.year - ((date.today().month, date.today().day) <
                                                       (body.birth_date.month, body.birth_date.day))
    if age > 120:
        raise HTTPException(422, "Tanggal lahir tidak valid.")
    if db.scalar(select(User.id).where(func.lower(User.username) == body.username.lower())) or _email_owner(db, body.email):
        raise HTTPException(409, "Username atau email sudah digunakan.")
    patient = User(username=body.username, password_hash=hash_password(body.password), role="pasien",
                   is_active=False)
    db.add(patient)
    try:
        db.flush()
        db.add(UserProfile(user_id=patient.id, full_name=body.full_name, birth_date=body.birth_date,
                           sex=body.sex, email=body.email))
        audit.append(db, patient.username, patient.role, "PATIENT_REGISTRATION_REQUESTED", None, "pending",
                     "Menunggu persetujuan admin atau auditor")
        db.commit()
    except Exception:
        db.rollback()
        # A concurrent request may claim the same unique username after the checks above.
        if db.scalar(select(User.id).where(func.lower(User.username) == body.username.lower())) or _email_owner(db, body.email):
            raise HTTPException(409, "Username atau email sudah digunakan.")
        raise
    return {"status": "menunggu_persetujuan", "username": patient.username,
            "message": "Pendaftaran diterima. Akun menunggu persetujuan admin atau auditor."}


@app.post("/auth/register/start", status_code=202, include_in_schema=settings.enable_email_otp_registration)
def registration_start(body: RegistrationStartIn, request: Request, db: Session = Depends(get_db)):
    if not settings.enable_email_otp_registration:
        raise HTTPException(410, "Pendaftaran melalui OTP sementara dinonaktifkan. Hubungi admin atau auditor untuk membuat akun.")
    email = body.email.strip().lower()
    ip = request.client.host if request.client else "?"
    if not registration_limiter.allow(f"{ip}:{email}"):
        raise HTTPException(429, "Terlalu banyak permintaan kode. Coba lagi nanti.")
    if body.birth_date > date.today():
        raise HTTPException(422, "Tanggal lahir tidak boleh di masa depan")
    if db.scalar(select(User.id).join(UserProfile, UserProfile.user_id == User.id).where(func.lower(UserProfile.email) == email)):
        raise HTTPException(409, "Email sudah terdaftar. Silakan masuk atau gunakan email lain.")
    otp = f"{secrets.randbelow(1_000_000):06d}"
    challenge_id = str(uuid.uuid4())
    challenge = EmailOtpChallenge(id=challenge_id, email=email, username="", password_hash=hash_password(body.password),
                                  full_name=body.full_name.strip(), birth_date=body.birth_date, sex=body.sex,
                                  address=body.address.strip(), phone=body.phone.strip(),
                                  otp_hash=_otp_digest(challenge_id, email, otp),
                                  expires_at=datetime.utcnow() + timedelta(minutes=10))
    db.execute(delete(EmailOtpChallenge).where(
        (EmailOtpChallenge.email == email) | (EmailOtpChallenge.expires_at < datetime.utcnow())
    ))
    db.add(challenge)
    db.commit()
    try:
        _send_registration_otp(email, otp)
    except Exception:
        db.delete(challenge)
        db.commit()
        raise
    return {"challenge_id": challenge_id, "expires_in": 600, "message": "Kode verifikasi dikirim ke email Anda."}


@app.post("/auth/register/verify", include_in_schema=settings.enable_email_otp_registration)
def registration_verify(body: RegistrationVerifyIn, db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    if not settings.enable_email_otp_registration:
        raise HTTPException(410, "Pendaftaran melalui OTP sementara dinonaktifkan. Hubungi admin atau auditor untuk membuat akun.")
    challenge = db.get(EmailOtpChallenge, body.challenge_id)
    if not challenge or challenge.expires_at < datetime.utcnow() or challenge.attempts >= 5:
        if challenge:
            db.delete(challenge)
            db.commit()
        raise HTTPException(400, "Kode tidak valid atau sudah kedaluwarsa. Minta kode baru.")
    if not hmac.compare_digest(challenge.otp_hash, _otp_digest(challenge.id, challenge.email, body.otp)):
        challenge.attempts += 1
        db.commit()
        raise HTTPException(400, "Kode verifikasi salah.")
    try:
        user = _create_self_service_patient(db, chain, full_name=challenge.full_name, email=challenge.email,
                                            password_hash=challenge.password_hash, birth_date=challenge.birth_date,
                                            sex=challenge.sex, address=challenge.address, phone=challenge.phone)
        db.delete(challenge)
        db.commit()
    except Exception:
        db.rollback()
        raise
    process_pending(db, chain)
    return {"access_token": create_token(user.id), "role": user.role, "username": user.username}


@app.post("/auth/google")
def google_auth(body: GoogleCredentialIn, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "?"
    if not google_limiter.allow(ip):
        raise HTTPException(429, "Terlalu banyak percobaan masuk dengan Google.")
    if not settings.google_client_id:
        raise HTTPException(503, "Google Sign-In belum dikonfigurasi oleh administrator.")
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
        claims = id_token.verify_oauth2_token(body.credential, google_requests.Request(), settings.google_client_id)
        if not claims.get("email_verified") or not claims.get("sub") or not claims.get("email"):
            raise ValueError("Google account email must be verified")
    except Exception as exc:
        raise HTTPException(401, "Verifikasi akun Google gagal. Silakan coba kembali.") from exc
    identity = db.scalar(select(AuthIdentity).where(AuthIdentity.provider == "google", AuthIdentity.subject == claims["sub"]))
    user = db.get(User, identity.user_id) if identity else None
    if not user:
        email = claims["email"].strip().lower()
        profile_user_id = db.scalar(select(UserProfile.user_id).where(func.lower(UserProfile.email) == email))
        if profile_user_id:
            user = db.get(User, profile_user_id)
            if user.role != "pasien":
                raise HTTPException(409, "Email ini sudah terhubung ke akun petugas. Hubungi administrator.")
        else:
            user = User(username=_username_for(db, claims.get("name", "Pasien"), email),
                        password_hash=hash_password(secrets.token_urlsafe(32)), role="pasien", is_active=False)
            db.add(user)
            db.flush()
            db.add(UserProfile(user_id=user.id, full_name=(claims.get("name") or "Pasien Google")[:120], email=email))
        db.add(AuthIdentity(user_id=user.id, provider="google", subject=claims["sub"]))
        db.commit()
    if user and user.role == "pasien" and not user.is_active and not user.patient_id:
        return {"approval_pending": True, "username": user.username,
                "message": "Akun menunggu persetujuan admin atau auditor."}
    if not user or not user.is_active:
        raise HTTPException(403, "Akun tidak aktif. Hubungi administrator.")
    return {"access_token": create_token(user.id), "role": user.role, "username": user.username,
            "profile_complete": bool(user.patient_id)}


@app.post("/auth/complete-registration")
def complete_google_registration(body: PatientOnboardingIn, user: User = Depends(require_role("pasien")),
                                 db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    if user.patient_id:
        raise HTTPException(409, "Profil pasien sudah lengkap.")
    profile = db.get(UserProfile, user.id)
    if not profile or not profile.email:
        raise HTTPException(422, "Akun Google tidak memiliki email terverifikasi.")
    try:
        profile.birth_date, profile.sex = body.birth_date, body.sex
        profile.address, profile.phone = body.address.strip(), body.phone.strip()
        rec = _attach_patient_record(db, chain, user, profile, body.birth_date, body.sex, body.address, body.phone)
        add_activity(db, rec.id, "registrasi", "Pasien melengkapi pendaftaran melalui Google.", user.username)
        audit.append(db, user.username, user.role, "GOOGLE_REGISTRATION_COMPLETED", rec.id, "pending")
        db.commit()
    except Exception:
        db.rollback()
        raise
    process_pending(db, chain)
    return {"ok": True, "patient_id": user.patient_id}


@app.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    result = _profile_out(user, db.get(UserProfile, user.id), db)
    photo = db.get(ProfilePhoto, user.id)
    result["photo_data_url"] = (f"data:{photo.content_type};base64,{base64.b64encode(photo.data).decode('ascii')}"
                                if photo else None)
    return result


@app.put("/me/profile-photo")
def set_my_profile_photo(body: ProfilePhotoIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in ("admin", "dokter", "auditor"):
        raise HTTPException(403, "Unggah foto profil hanya tersedia untuk admin, dokter, dan auditor")
    try:
        image = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "Data foto tidak valid")
    if len(image) > 2 * 1024 * 1024:
        raise HTTPException(413, "Ukuran foto maksimal 2 MB")
    signatures = {
        "image/jpeg": image.startswith(b"\xff\xd8\xff"),
        "image/png": image.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": len(image) >= 12 and image[:4] == b"RIFF" and image[8:12] == b"WEBP",
    }
    if not signatures[body.content_type]:
        raise HTTPException(415, "Format foto tidak cocok. Gunakan JPEG, PNG, atau WebP")
    photo = db.get(ProfilePhoto, user.id)
    if photo is None:
        photo = ProfilePhoto(user_id=user.id, content_type=body.content_type, data=image)
        db.add(photo)
    else:
        photo.content_type, photo.data, photo.updated_at = body.content_type, image, datetime.utcnow()
    audit.append(db, user.username, user.role, "PROFILE_PHOTO_UPDATED", str(user.id), "ok")
    db.commit()
    return {"saved": True}


# ---------- rekam medis ----------
def _out(rec: Record) -> dict:  # salt tidak pernah dikirim ke klien
    return {"id": rec.id, "pseudo_id": rec.pseudo_id, "age": rec.age, "sex": rec.sex, "history": rec.history,
            "diagnosis": rec.diagnosis, "notes": rec.notes, "version": rec.version}


@app.get("/records")
def list_records(user: User = Depends(current_user), db: Session = Depends(get_db)):
    result = []
    for rec in db.scalars(select(Record).order_by(Record.pseudo_id)):
        if not _allowed(db, user, rec, "read"):
            continue
        profile = db.get(PatientProfile, rec.id)
        owner = db.scalar(select(User).where(User.patient_id == rec.id))
        user_profile = db.get(UserProfile, owner.id) if owner else None
        care = db.get(PatientCare, rec.id)
        episode = active_episode(db, rec.id)
        doctor = db.get(User, episode.doctor_id) if episode and episode.doctor_id else None
        assignment = db.get(PatientDoctorAssignment, rec.id)
        assigned = db.get(User, assignment.doctor_id) if assignment and assignment.doctor_id else None
        assigned_profile = db.get(UserProfile, assigned.id) if assigned else None
        doctor_profile = db.get(UserProfile, doctor.id) if doctor else None
        result.append({"id": rec.id, "pseudo_id": rec.pseudo_id,
                       "patient_name": profile.full_name if profile else (user_profile.full_name if user_profile else "Nama belum diisi"),
                       "age": rec.age, "sex": rec.sex, "version": rec.version,
                       "can_edit": _allowed(db, user, rec, "write"),
                       "care_status": care.status if care else "rawat_jalan", "room": care.room if care else "Belum ditentukan",
                       "doctor_name": (doctor_profile.full_name if doctor_profile else doctor.username) if doctor else ((assigned_profile.full_name if assigned_profile else assigned.username) if assigned else (episode.doctor_name if episode else "")),
                       "specialty": episode.specialty if episode else (assignment.specialty if assignment else ""),
                       "ecg_available": ecg_is_available(db, rec.id, care.status if care else "rawat_jalan")})
    return result


@app.post("/records", status_code=201)
def create_record(body: RecordIn, user: User = Depends(require_role("dokter")),
                  db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    rec = services.create_record(db, chain, user, body)
    db.add(PatientDoctorAssignment(patient_id=rec.id, doctor_id=user.id,
                                   specialty=(db.get(DoctorSpecialty, user.id).specialty
                                              if db.get(DoctorSpecialty, user.id) else "Dokter Umum"),
                                   assigned_by=user.username))
    add_activity(db, rec.id, "registrasi", "Rekam medis awal dibuat oleh dokter.", user.username)
    db.commit()
    process_pending(db, chain)
    return {**_out(rec), "chain_sync_pending": _pending_chain_count(db, rec.id) > 0}


@app.get("/records/{rid}")
def get_record(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "read")
    audit.append(db, user.username, user.role, "READ", rec.id, "ok")
    db.commit()
    return _out(rec)


@app.get("/records/{rid}/diagnosis.pdf")
def download_diagnosis_pdf(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db),
                           chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "read")
    diagnosis = (rec.diagnosis or "").strip()
    if diagnosis.casefold() in ("", "belum ada diagnosis", "belum diisi", "belum ditentukan", "unknown"):
        raise HTTPException(409, "PDF belum tersedia karena diagnosis pasien belum dicatat.")

    patient = db.get(PatientProfile, rec.id)
    care = db.get(PatientCare, rec.id)
    episode = active_episode(db, rec.id)
    assignment = db.get(PatientDoctorAssignment, rec.id)
    doctor_id = episode.doctor_id if episode and episode.doctor_id else (assignment.doctor_id if assignment else None)
    doctor = db.get(User, doctor_id) if doctor_id else None
    doctor_profile = db.get(UserProfile, doctor.id) if doctor else None
    doctor_name = (doctor_profile.full_name if doctor_profile else doctor.username) if doctor else "Belum ditentukan"
    diagnosis_event = db.scalar(select(PatientActivity).where(
        PatientActivity.patient_id == rec.id,
        PatientActivity.activity_type == "diagnosis",
    ).order_by(PatientActivity.occurred_at.desc()).limit(1))
    diagnosis_date = diagnosis_event.occurred_at if diagnosis_event else (episode.admitted_at if episode else None)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("MediChainTitle", parent=styles["Title"], fontName="Helvetica-Bold",
                                 fontSize=18, leading=22, textColor=colors.HexColor("#087f83"), alignment=TA_CENTER,
                                 spaceAfter=5 * mm)
    section_style = ParagraphStyle("MediChainSection", parent=styles["Heading2"], fontName="Helvetica-Bold",
                                   fontSize=11, leading=14, textColor=colors.HexColor("#087f83"),
                                   spaceBefore=4 * mm, spaceAfter=2 * mm)
    body_style = ParagraphStyle("MediChainBody", parent=styles["BodyText"], fontName="Helvetica",
                                fontSize=10, leading=15, textColor=colors.HexColor("#203741"),
                                wordWrap="CJK", splitLongWords=1)
    label_style = ParagraphStyle("MediChainLabel", parent=body_style, fontName="Helvetica-Bold",
                                 textColor=colors.HexColor("#526a73"))

    def para(value, style=body_style):
        # Built-in ReportLab fonts use WinAnsi; keep printable text within that encoding.
        text = str(value or "-").encode("latin-1", "replace").decode("latin-1")
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm,
                                 topMargin=18 * mm, bottomMargin=18 * mm,
                                 title=f"Diagnosis - {rec.pseudo_id}", author="MediChain")
    story = [para("MEDICHAIN", title_style), para("Ringkasan Diagnosis Pasien", section_style), Spacer(1, 2 * mm)]
    patient_rows = [
        [para("Nama pasien", label_style), para(patient.full_name if patient else rec.pseudo_id),
         para("Kode rekam", label_style), para(rec.pseudo_id)],
        [para("Usia", label_style), para(f"{rec.age} tahun"), para("Jenis kelamin", label_style),
         para("Laki-laki" if rec.sex == "L" else "Perempuan" if rec.sex == "P" else "-")],
        [para("Dokter", label_style), para(doctor_name), para("Tanggal pemeriksaan", label_style),
         para(diagnosis_date.strftime("%d-%m-%Y %H:%M") if diagnosis_date else "Tidak tercatat")],
        [para("Status perawatan", label_style), para(care.status.replace("_", " ").title() if care else "Tidak tercatat"),
         para("Ruangan", label_style), para(care.room if care else "Tidak tercatat")],
    ]
    patient_table = Table(patient_rows, colWidths=[28 * mm, 55 * mm, 31 * mm, 46 * mm], hAlign="LEFT")
    patient_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f7f8")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f1f7f8")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dce7e9")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dce7e9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([patient_table, para("Diagnosis", section_style), para(diagnosis)])
    story.extend([para("Riwayat kesehatan", section_style), para(rec.history or "Belum ada catatan.")])
    story.extend([para("Catatan tindak lanjut", section_style), para(rec.notes or "Belum ada catatan.")])
    allergies = list(db.scalars(select(PatientAllergy).where(PatientAllergy.patient_id == rid).order_by(PatientAllergy.created_at.desc())))
    story.append(para("Alergi", section_style))
    story.append(para("; ".join(f"{x.substance} ({x.reaction or 'reaksi belum dicatat'}, {x.severity}, {'aktif' if x.status == 'active' else 'selesai'})" for x in allergies)
                     if allergies else "Tidak ada alergi yang tercatat."))
    medications = list(db.scalars(select(MedicationOrder).where(MedicationOrder.patient_id == rid).order_by(MedicationOrder.created_at.desc())))
    story.append(para("Instruksi terapi", section_style))
    story.append(para(" | ".join(f"{x.medication} - {x.dose}; {x.route}; {x.frequency}; status {x.status}" for x in medications)
                     if medications else "Belum ada instruksi terapi."))
    diagnostics = list(db.scalars(select(DiagnosticOrder).where(DiagnosticOrder.patient_id == rid).order_by(DiagnosticOrder.ordered_at.desc())))
    story.append(para("Pemeriksaan penunjang", section_style))
    story.append(para(" | ".join(f"{x.test_name} ({'laboratorium' if x.kind == 'lab' else 'radiologi'}) - {x.status}" + (f"; hasil: {x.result}" if x.result else "") for x in diagnostics)
                     if diagnostics else "Belum ada permintaan pemeriksaan penunjang."))
    footnote_style = ParagraphStyle("MediChainFootnote", parent=body_style, fontSize=8, leading=11,
                                    textColor=colors.HexColor("#687d85"))
    story.extend([Spacer(1, 9 * mm), para(
        f"Dicetak dari MediChain pada {datetime.now().strftime('%d-%m-%Y %H:%M')}. "
        "Dokumen ini merupakan ringkasan rekam medis dan bukan resep atau surat keterangan resmi.", footnote_style)])
    document.build(story)

    audit.append(db, user.username, user.role, "DiagnosisPdfExported", rec.id, "ok", f"versi={rec.version}")
    db.commit()
    return Response(output.getvalue(), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="MediChain-Diagnosis-{rec.pseudo_id}.pdf"',
        "Cache-Control": "no-store",
    })


@app.get("/records/{rid}/fhir")
def export_record_fhir(rid: str, scope: str = "summary", user: User = Depends(current_user),
                       db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    if scope not in ("summary", "full"):
        raise HTTPException(422, "Scope FHIR harus summary atau full")
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "read")
    audit.append(db, user.username, user.role, "FHIRExported", rec.id, "ok", f"scope={scope}")
    payload = _fhir_bundle(db, chain, rec, scope)["bundle"]
    db.commit()
    return Response(content=json.dumps(payload, ensure_ascii=False), media_type="application/fhir+json")


def _share_out(db: Session, share: RecordShare) -> dict:
    accesses = list(db.scalars(select(RecordShareAccess).where(
        RecordShareAccess.share_id == share.id
    ).order_by(RecordShareAccess.accessed_at.desc()).limit(30)))
    return {"id": share.id, "scope": share.scope, "purpose": share.purpose,
            "created_at": share.created_at.isoformat() + "Z", "expires_at": share.expires_at.isoformat() + "Z",
            "revoked_at": share.revoked_at.isoformat() + "Z" if share.revoked_at else None,
            "access_count": share.access_count, "last_accessed_at": share.last_accessed_at.isoformat() + "Z" if share.last_accessed_at else None,
            "accesses": [{"accessed_at": item.accessed_at.isoformat() + "Z", "outcome": item.outcome} for item in accesses]}


def _require_share_owner(user: User, rid: str) -> None:
    if user.role != "pasien" or user.patient_id != rid:
        raise HTTPException(403, "Hanya pasien pemilik rekam yang dapat mengelola izin berbagi")


@app.get("/records/{rid}/shares")
def list_record_shares(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _record(db, rid)
    _require_share_owner(user, rid)
    shares = db.scalars(select(RecordShare).where(RecordShare.patient_id == rid).order_by(RecordShare.created_at.desc()))
    return [_share_out(db, share) for share in shares]


@app.post("/records/{rid}/shares", status_code=201)
def create_record_share(rid: str, body: RecordShareIn, request: Request,
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    rec = _record(db, rid)
    _require_share_owner(user, rid)
    token = secrets.token_urlsafe(32)
    share = RecordShare(id=str(uuid.uuid4()), patient_id=rid, created_by=user.id,
                        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
                        scope=body.scope, purpose=body.purpose,
                        expires_at=datetime.utcnow() + timedelta(minutes=body.expires_minutes))
    db.add(share)
    audit.append(db, user.username, user.role, "PatientShareCreated", rec.id, "ok", f"scope={body.scope}")
    # QR dibuat lokal oleh backend; link bearer hanya disimpan dalam bentuk hash.
    origin = request.headers.get("origin", "").rstrip("/")
    trusted_origins = set(settings.cors_origins) | {settings.public_app_url}
    app_url = origin if origin in trusted_origins else settings.public_app_url
    share_url = f"{app_url}/share#{token}"
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=5, border=2)
        qr.add_data(share_url)
        qr.make(fit=True)
        image = qr.make_image(image_factory=SvgPathImage)
        qr_buffer = BytesIO()
        image.save(qr_buffer)
        qr_svg = qr_buffer.getvalue().decode("utf-8")
    except ImportError as exc:
        db.rollback()
        raise HTTPException(503, "Pembuat QR belum terpasang. Pasang dependensi qrcode lalu mulai ulang API.") from exc
    db.commit()
    return {**_share_out(db, share), "share_url": share_url, "qr_svg": qr_svg}


@app.delete("/records/{rid}/shares/{share_id}")
def revoke_record_share(rid: str, share_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _record(db, rid)
    _require_share_owner(user, rid)
    share = db.get(RecordShare, share_id)
    if not share or share.patient_id != rid:
        raise HTTPException(404, "Tautan berbagi tidak ditemukan")
    if not share.revoked_at:
        share.revoked_at = datetime.utcnow()
        audit.append(db, user.username, user.role, "PatientShareRevoked", rid, "ok", f"share={share.id}")
        db.commit()
    return {"revoked": True}


@app.post("/share/access")
def open_shared_record(body: ShareAccessIn, request: Request, db: Session = Depends(get_db),
                       chain: ChainClient = Depends(get_chain)):
    remote = request.client.host if request.client else "unknown"
    if not share_limiter.allow(remote):
        raise HTTPException(429, "Terlalu banyak percobaan membuka tautan. Coba lagi sebentar.")
    digest = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
    share = db.scalar(select(RecordShare).where(RecordShare.token_hash == digest))
    if not share:
        raise HTTPException(404, "Tautan berbagi tidak valid")
    now = datetime.utcnow()
    outcome = "opened"
    if share.revoked_at:
        outcome = "revoked"
    elif share.expires_at <= now:
        outcome = "expired"
    access = RecordShareAccess(share_id=share.id, outcome=outcome)
    db.add(access)
    if outcome != "opened":
        db.commit()
        raise HTTPException(410, "Tautan berbagi sudah dicabut atau kedaluwarsa")
    rec = _record(db, share.patient_id)
    share.access_count += 1
    share.last_accessed_at = now
    audit.append(db, "shared-link", None, "PatientShareOpened", rec.id, "ok", f"scope={share.scope}")
    result = _fhir_bundle(db, chain, rec, share.scope)
    db.commit()
    return {**result, "purpose": share.purpose, "expires_at": share.expires_at.isoformat() + "Z"}


@app.put("/records/{rid}")
def update_record(rid: str, body: RecordUpdateIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    rec = _record_for_update(db, rid)
    _guard(db, chain, user, rec, "write")
    if _pending_chain_count(db, rec.id):
        process_pending(db, chain)
    if _pending_chain_count(db, rec.id):
        raise HTTPException(503, "Pembaruan sebelumnya masih menunggu blockchain; coba lagi setelah sinkronisasi.")
    # Jangan "mencuci" data yang sudah dimanipulasi: pembaruan sah hanya boleh bila data saat ini masih valid.
    if services.check_integrity(db, chain, rec)["status"] != "valid":
        audit.append(db, user.username, user.role, "UPDATE", rec.id, "denied", "data tidak valid terhadap hash on-chain")
        db.commit()
        raise HTTPException(409, "Data terindikasi termodifikasi. Selesaikan investigasi sebelum memperbarui.")
    old_diagnosis = rec.diagnosis
    for f in ("history", "diagnosis", "notes"):
        v = getattr(body, f)
        if v is not None:
            setattr(rec, f, v)
    if body.diagnosis is not None and body.diagnosis != old_diagnosis:
        episode = active_episode(db, rec.id)
        add_activity(db, rec.id, "diagnosis", "Diagnosis klinis diperbarui.", user.username, episode)
    expected_version = rec.version
    rec.version += 1
    hr, he = services.local_hashes(db, rec)
    enqueue_record_update(db, rec.id, chain_key(rec.id), hr, he, expected_version, user.username, user.role)
    audit.append(db, user.username, user.role, "RecordUpdated", rec.id, "pending",
                 f"versi {rec.version} menunggu konfirmasi blockchain")
    db.commit()
    process_pending(db, chain)
    return {**_out(rec), "chain_sync_pending": _pending_chain_count(db, rec.id) > 0}


@app.get("/records/{rid}/ecg")
def get_ecg(rid: str, start: float = 0, duration: float = 5, user: User = Depends(current_user),
            db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "read")
    if not ecg_is_available(db, rid):
        raise HTTPException(403, "ECG hanya tersedia untuk pasien rawat inap atau dalam pemulihan pascaoperasi")
    b = db.get(Biosignal, rid)
    s = json.loads(b.samples)
    a = max(0, int(start * b.fs))
    e = min(len(s), a + max(1, min(int(duration * b.fs), 60 * b.fs)))
    audit.append(db, user.username, user.role, "READ_ECG", rec.id, "ok")
    db.commit()
    return {"fs": b.fs, "start": a / b.fs, "samples": s[a:e]}


@app.post("/records/{rid}/verify")
def verify(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    if user.role not in ("admin", "auditor"):
        raise HTTPException(403, "Hanya admin dan auditor yang dapat menjalankan verifikasi integritas")
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "read")
    res = _integrity_result(db, chain, rec)
    audit.append(db, user.username, user.role, "verifyRecord", rec.id, "ok", res["status"])
    db.commit()
    return res


@app.get("/records/{rid}/integrity")
def read_integrity(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "read")
    return _integrity_result(db, chain, rec)


@app.get("/chain/status")
def chain_status(user: User = Depends(require_role("admin", "auditor")), db: Session = Depends(get_db)):
    pending = list(db.scalars(select(ChainOperation).where(ChainOperation.status == "pending")
                              .order_by(ChainOperation.id).limit(100)))
    info = chain_metadata()
    return {"mode": info["mode"], "network": info["network"], "chain_id": info["chain_id"],
            "pending_count": _pending_chain_count(db),
            "pending_operations": [{"id": item.id, "operation": item.operation,
                                    "record_id": item.record_id, "attempts": item.attempts,
                                    "last_error": item.last_error} for item in pending]}


@app.post("/chain/sync")
def sync_chain(user: User = Depends(require_role("admin", "auditor")),
               db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    completed = process_pending(db, chain, limit=100)
    return {"completed": completed, "pending_count": _pending_chain_count(db)}


# ---------- manajemen akun (admin dan auditor) ----------
def _profile_out(user: User, profile: UserProfile | None, db: Session | None = None) -> dict:
    doctor = db.get(DoctorSpecialty, user.id) if db and user.role == "dokter" else None
    approval_status = ("menunggu_persetujuan" if user.role == "pasien" and not user.is_active and not user.patient_id
                       else "aktif" if user.is_active else "nonaktif")
    return {"id": user.id, "username": user.username, "role": user.role, "is_active": user.is_active,
            "approval_status": approval_status,
            "patient_id": user.patient_id, "full_name": profile.full_name if profile else user.username,
            "birth_date": profile.birth_date.isoformat() if profile and profile.birth_date else None, "sex": profile.sex if profile else None,
            "address": profile.address if profile else "", "phone": profile.phone if profile else "",
            "specialty": doctor.specialty if doctor else "",
            "email": profile.email if profile else ""}


@app.get("/users")
def list_users(user: User = Depends(require_role("admin", "auditor")), db: Session = Depends(get_db)):
    return [_profile_out(u, db.get(UserProfile, u.id), db) for u in db.scalars(select(User).order_by(User.id))]


@app.post("/users", status_code=201)
def create_user(body: UserCreateIn, user: User = Depends(require_role("admin", "auditor")),
                db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    if db.scalar(select(User).where(func.lower(User.username) == body.username.lower())):
        raise HTTPException(409, "Username sudah digunakan")
    if body.email.strip() and _email_owner(db, body.email):
        raise HTTPException(409, "Email sudah digunakan")
    if body.role == "pasien" and (not body.birth_date or not body.sex):
        raise HTTPException(422, "Tanggal lahir dan jenis kelamin wajib untuk akun pasien")
    if body.birth_date and body.birth_date > date.today():
        raise HTTPException(422, "Tanggal lahir tidak boleh di masa depan")
    new_user = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(new_user)
    db.flush()
    profile = UserProfile(user_id=new_user.id, full_name=body.full_name,
                          birth_date=body.birth_date,
                          sex=body.sex, address=body.address, phone=body.phone, email=body.email)
    db.add(profile)
    if body.role == "dokter":
        db.add(DoctorSpecialty(user_id=new_user.id, specialty=body.specialty or "Penyakit Dalam"))
    if body.role == "pasien":
        today = date.today()
        age = today.year - body.birth_date.year - ((today.month, today.day) < (body.birth_date.month, body.birth_date.day))
        if age > 120:
            raise HTTPException(422, "Usia pasien harus 120 tahun atau kurang")
        data = RecordIn(age=age, sex=body.sex, history="Profil pasien baru", diagnosis="Belum ada diagnosis",
                        notes="Rekam dibuat saat akun pasien didaftarkan.",
                        ecg={"fs": 250, "samples": services.make_patient_ecg(new_user.id * 7919)})
        doctor, specialty = choose_doctor(db, data.diagnosis, data.history)
        rec = services.create_record(db, chain, user, data)
        new_user.patient_id = rec.id
        db.add(PatientDoctorAssignment(patient_id=rec.id, doctor_id=doctor.id,
                                       specialty=specialty, assigned_by=user.username))
        access = db.get(Access, (rec.id, "pasien"))
        access.allowed = True
        db.add(PatientProfile(record_id=rec.id, full_name=body.full_name, birth_date=body.birth_date,
                              sex=body.sex, address=body.address, phone=body.phone, email=body.email))
        add_activity(db, rec.id, "registrasi", "Akun pasien dan rekam medis dibuat.", user.username)
        enqueue_access(db, rec.id, chain_key(rec.id), role_hash("pasien"), True, user.username, user.role)
        audit.append(db, user.username, user.role, "PatientAccessGranted", rec.id, "pending",
                     "akun pasien dibuat; izin blockchain menunggu konfirmasi")
    if body.role == "dokter":
        db.flush()
        ensure_patient_doctor_assignments(db, user.username)
    audit.append(db, user.username, user.role, "UserCreated", new_user.patient_id, "ok", f"{body.role}: {body.username}")
    db.commit()
    process_pending(db, chain)
    return {**_profile_out(new_user, profile, db), "chain_sync_pending": _pending_chain_count(db, new_user.patient_id) > 0 if new_user.patient_id else False}


@app.post("/users/{user_id}/approve")
def approve_patient_registration(user_id: int, actor: User = Depends(require_role("admin", "auditor")),
                                 db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    target = db.get(User, user_id)
    if not target or target.role != "pasien":
        raise HTTPException(404, "Permintaan pendaftaran pasien tidak ditemukan")
    if target.is_active or target.patient_id:
        raise HTTPException(409, "Akun pasien sudah diproses")
    profile = db.get(UserProfile, target.id)
    if not profile or not profile.birth_date or not profile.sex:
        raise HTTPException(422, "Lengkapi tanggal lahir dan jenis kelamin sebelum menyetujui akun")
    if _email_owner(db, profile.email, exclude_user_id=target.id):
        raise HTTPException(409, "Email sudah terhubung ke akun lain")
    try:
        rec = _attach_patient_record(db, chain, target, profile, profile.birth_date, profile.sex,
                                     profile.address, profile.phone, audit_registration=False)
        target.is_active = True
        audit.append(db, actor.username, actor.role, "PatientAccountActivated", rec.id, "ok",
                     f"Pendaftaran pasien disetujui: {target.username}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    process_pending(db, chain)
    return {**_profile_out(target, profile, db), "chain_sync_pending": _pending_chain_count(db, rec.id) > 0}


@app.put("/users/{user_id}")
def update_user(user_id: int, body: UserUpdateIn, actor: User = Depends(require_role("admin", "auditor")),
                db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "Pengguna tidak ditemukan")
    profile = db.get(UserProfile, target.id)
    if not profile:
        profile = UserProfile(user_id=target.id, full_name=target.username)
        db.add(profile)
    changes = body.model_dump(exclude_unset=True)
    next_username = changes.pop("username", None)
    next_specialty = changes.pop("specialty", None)
    if next_username and next_username != target.username:
        username_owner = db.scalar(select(User).where(func.lower(User.username) == next_username.lower()))
        if username_owner and username_owner.id != target.id:
            raise HTTPException(409, "Username sudah digunakan")
        target.username = next_username
    next_role = changes.pop("role", None)
    if target.role == "pasien" and not target.patient_id:
        if next_role and next_role != "pasien":
            raise HTTPException(422, "Akun pendaftaran pasien tidak dapat diubah menjadi akun petugas")
        if changes.get("is_active") is True:
            raise HTTPException(409, "Gunakan aksi persetujuan agar rekam medis dibuat dengan aman")
    if changes.get("email") and _email_owner(db, changes["email"], exclude_user_id=target.id):
        raise HTTPException(409, "Email sudah digunakan")
    will_be_admin = next_role == "admin" if next_role else target.role == "admin"
    will_be_active = changes.get("is_active", target.is_active)
    if target.role == "admin" and target.is_active and not (will_be_admin and will_be_active):
        active_admins = list(db.scalars(select(User).where(User.role == "admin", User.is_active)))
        if len(active_admins) <= 1:
            raise HTTPException(409, "Admin aktif terakhir tidak dapat dinonaktifkan atau diturunkan perannya")
    if next_role and (next_role == "pasien") != (target.patient_id is not None):
        raise HTTPException(422, "Peran pasien hanya dapat digunakan untuk akun yang terhubung ke rekam pasien")
    if next_role:
        target.role = next_role
    if target.role == "dokter":
        specialty = db.get(DoctorSpecialty, target.id)
        if not specialty:
            specialty = DoctorSpecialty(user_id=target.id, specialty=next_specialty or "Penyakit Dalam")
            db.add(specialty)
        elif next_specialty:
            specialty.specialty = next_specialty
    else:
        specialty = db.get(DoctorSpecialty, target.id)
        if specialty:
            db.delete(specialty)
    if target.patient_id and any(k in changes and changes[k] is None for k in ("birth_date", "sex")):
        raise HTTPException(422, "Tanggal lahir dan jenis kelamin pasien tidak boleh dikosongkan")
    if changes.get("birth_date") and changes["birth_date"] > date.today():
        raise HTTPException(422, "Tanggal lahir tidak boleh di masa depan")
    if "is_active" in changes:
        target.is_active = changes.pop("is_active")
    if target.role != "dokter" or not target.is_active:
        db.flush()
        ensure_patient_doctor_assignments(db, actor.username)
    demographic_change = False
    for key, value in changes.items():
        if key in ("birth_date", "sex") and value is not None:
            demographic_change = demographic_change or getattr(profile, key) != value
        setattr(profile, key, value)
    if demographic_change and target.patient_id:
        rec = _record_for_update(db, target.patient_id)
        if _pending_chain_count(db, rec.id):
            process_pending(db, chain)
        if _pending_chain_count(db, rec.id):
            raise HTTPException(503, "Perubahan pasien sebelumnya masih menunggu blockchain; coba lagi setelah sinkronisasi.")
        if services.check_integrity(db, chain, rec)["status"] != "valid":
            raise HTTPException(409, "Rekam pasien terindikasi termodifikasi; investigasi sebelum mengubah demografi")
        if profile.birth_date:
            dob = profile.birth_date
            today = date.today()
            rec.age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            if rec.age > 120:
                raise HTTPException(422, "Usia pasien harus 120 tahun atau kurang")
        if profile.sex:
            rec.sex = profile.sex
        rec.version += 1
        hr, he = services.local_hashes(db, rec)
        enqueue_record_update(db, rec.id, chain_key(rec.id), hr, he, rec.version - 1,
                              actor.username, actor.role)
        audit.append(db, actor.username, actor.role, "PatientDemographicsUpdated", rec.id, "pending",
                     "rekam diperbarui; menunggu konfirmasi blockchain")
    if target.patient_id:
        patient_profile = db.get(PatientProfile, target.patient_id)
        if not patient_profile:
            patient_profile = PatientProfile(record_id=target.patient_id, full_name=profile.full_name,
                                             birth_date=profile.birth_date, sex=profile.sex,
                                             address=profile.address, phone=profile.phone, email=profile.email)
            db.add(patient_profile)
        for key in ("full_name", "birth_date", "sex", "address", "phone", "email"):
            if key in changes:
                setattr(patient_profile, key, changes[key])
    audit.append(db, actor.username, actor.role, "UserUpdated", target.patient_id, "ok", target.username)
    db.commit()
    process_pending(db, chain)
    return {**_profile_out(target, profile, db), "chain_sync_pending": _pending_chain_count(db, target.patient_id) > 0 if target.patient_id else False}


@app.put("/users/{user_id}/password")
def set_user_password(user_id: int, body: PasswordUpdateIn,
                      actor: User = Depends(require_role("admin", "auditor")), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "Pengguna tidak ditemukan")
    target.password_hash = hash_password(body.password)
    target.failed_logins, target.locked_until = 0, 0
    audit.append(db, actor.username, actor.role, "PasswordReset", target.patient_id, "ok", target.username)
    db.commit()
    return {"updated": True}


@app.delete("/users/{user_id}")
def delete_user(user_id: int, actor: User = Depends(require_role("admin", "auditor")),
                db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "Pengguna tidak ditemukan")
    if target.id == actor.id:
        raise HTTPException(409, "Anda tidak dapat menghapus akun yang sedang digunakan")
    if target.role == "admin" and target.is_active:
        admins = list(db.scalars(select(User).where(User.role == "admin", User.is_active)))
        if len(admins) <= 1:
            raise HTTPException(409, "Akun admin aktif terakhir tidak dapat dihapus")
    patient_id = target.patient_id if target.role == "pasien" else None
    if patient_id:
        other_owner = db.scalar(select(User.id).where(User.patient_id == patient_id, User.id != target.id))
        if other_owner:
            raise HTTPException(409, "Rekam pasien masih terhubung ke akun lain dan tidak dapat dihapus")
    username = target.username
    db.delete(target)
    db.flush()
    ensure_patient_doctor_assignments(db, actor.username)
    if patient_id:
        erase_patient_record(db, chain, patient_id, actor.username, actor.role)
    audit.append(db, actor.username, actor.role, "UserDeleted", patient_id, "ok", username)
    db.commit()
    process_pending(db, chain)
    return {"deleted": True}


# ---------- tagihan ----------
def _invoice_out(db: Session, invoice: Invoice) -> dict:
    rec = db.get(Record, invoice.patient_id)
    patient_profile = db.get(PatientProfile, invoice.patient_id)
    patient = db.scalar(select(User).where(User.patient_id == invoice.patient_id))
    profile = db.get(UserProfile, patient.id) if patient else None
    proof = db.execute(select(InvoicePaymentProof.id, InvoicePaymentProof.status,
                             InvoicePaymentProof.rejection_reason, InvoicePaymentProof.submitted_at)
                       .where(InvoicePaymentProof.invoice_id == invoice.id)
                       .order_by(InvoicePaymentProof.id.desc()).limit(1)).first()
    return {"id": invoice.id, "patient_id": invoice.patient_id,
            "patient_name": patient_profile.full_name if patient_profile else (profile.full_name if profile else (patient.username if patient else "Nama belum diisi")),
            "pseudo_id": rec.pseudo_id, "description": invoice.description, "amount": float(invoice.amount),
            "due_date": invoice.due_date, "status": invoice.status, "created_by": invoice.created_by,
            "payment_proof_id": proof.id if proof else None,
            "payment_proof_status": proof.status if proof else None,
            "payment_proof_rejection_reason": proof.rejection_reason if proof and proof.status == "rejected" else "",
            "payment_proof_submitted_at": proof.submitted_at.isoformat() if proof else None}


@app.get("/invoices")
def list_invoices(user: User = Depends(current_user), db: Session = Depends(get_db)):
    invoices = db.scalars(select(Invoice).order_by(Invoice.due_date, Invoice.id))
    if user.role == "pasien":
        invoices = [i for i in invoices if i.patient_id == user.patient_id]
    elif user.role == "dokter":
        allowed = {r.id for r in db.scalars(select(Record)) if _allowed(db, user, r, "read")}
        invoices = [i for i in invoices if i.patient_id in allowed]
    return [_invoice_out(db, invoice) for invoice in invoices]


@app.post("/invoices", status_code=201)
def create_invoice(body: InvoiceIn, user: User = Depends(require_role("admin", "auditor")), db: Session = Depends(get_db)):
    _record(db, body.patient_id)
    invoice = Invoice(patient_id=body.patient_id, description=body.description, amount=body.amount,
                      due_date=body.due_date.isoformat(), status="belum_lunas", created_by=user.username)
    db.add(invoice)
    db.flush()
    audit.append(db, user.username, user.role, "InvoiceCreated", body.patient_id, "ok", f"tagihan #{invoice.id}")
    db.commit()
    return _invoice_out(db, invoice)


@app.put("/invoices/{invoice_id}")
def update_invoice(invoice_id: int, body: InvoiceUpdateIn, user: User = Depends(require_role("admin", "auditor")), db: Session = Depends(get_db)):
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if not invoice:
        raise HTTPException(404, "Tagihan tidak ditemukan")
    changes = body.model_dump(exclude_unset=True)
    if "amount" in changes and changes["amount"] is None:
        raise HTTPException(422, "Jumlah tagihan tidak boleh kosong.")
    amount_changed = "amount" in changes and changes["amount"] != invoice.amount
    if amount_changed:
        if invoice.status == "lunas":
            raise HTTPException(409, "Jumlah tagihan lunas tidak dapat diubah.")
        if db.scalar(select(InvoicePaymentProof.id).where(
                InvoicePaymentProof.invoice_id == invoice.id, InvoicePaymentProof.status == "pending")):
            raise HTTPException(409, "Jumlah tagihan tidak dapat diubah selama bukti pembayaran menunggu verifikasi.")
    for key, value in changes.items():
        setattr(invoice, key, value.isoformat() if key == "due_date" and value else value)
    audit.append(db, user.username, user.role, "InvoiceUpdated", invoice.patient_id, "ok", f"tagihan #{invoice.id}")
    db.commit()
    return _invoice_out(db, invoice)

@app.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: int, user: User = Depends(require_role("admin", "auditor")), db: Session = Depends(get_db)):
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if not invoice:
        raise HTTPException(404, "Tagihan tidak ditemukan")
    if db.scalar(select(InvoicePaymentProof.id).where(InvoicePaymentProof.invoice_id == invoice.id)):
        raise HTTPException(409, "Tagihan dengan riwayat bukti pembayaran tidak dapat dihapus.")
    patient_id = invoice.patient_id
    db.delete(invoice)
    audit.append(db, user.username, user.role, "InvoiceDeleted", patient_id, "ok", f"tagihan #{invoice_id}")
    db.commit()
    return {"deleted": True}


@app.post("/invoices/{invoice_id}/payment-proofs", status_code=201)
def submit_invoice_payment_proof(invoice_id: int, body: InvoicePaymentProofIn,
                                 user: User = Depends(require_role("pasien")), db: Session = Depends(get_db)):
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if not invoice or invoice.patient_id != user.patient_id:
        raise HTTPException(404, "Tagihan tidak ditemukan")
    if invoice.status == "lunas":
        raise HTTPException(409, "Tagihan ini sudah lunas.")
    existing_pending = db.scalar(select(InvoicePaymentProof.id).where(
        InvoicePaymentProof.invoice_id == invoice.id, InvoicePaymentProof.status == "pending").limit(1))
    if existing_pending:
        raise HTTPException(409, "Bukti pembayaran sebelumnya masih menunggu verifikasi admin.")
    try:
        image = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "Format bukti pembayaran tidak valid.")
    if len(image) > 2 * 1024 * 1024:
        raise HTTPException(413, "Ukuran bukti pembayaran maksimal 2 MB.")
    signatures = {
        "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
        "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": lambda data: len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    }
    if not signatures[body.content_type](image):
        raise HTTPException(422, "Isi file tidak cocok dengan format gambar yang dipilih.")
    proof = InvoicePaymentProof(invoice_id=invoice.id, submitted_by=user.id, amount=invoice.amount,
                                content_type=body.content_type, data=image, status="pending")
    db.add(proof)
    db.flush()
    audit.append(db, user.username, user.role, "InvoicePaymentProofSubmitted", invoice.patient_id,
                 "pending", f"bukti pembayaran tagihan #{invoice.id}")
    db.commit()
    return {"id": proof.id, "invoice_id": invoice.id, "status": proof.status,
            "submitted_at": proof.submitted_at.isoformat()}


@app.get("/payment-proofs/{proof_id}")
def get_invoice_payment_proof(proof_id: int, user: User = Depends(require_role("admin")),
                              db: Session = Depends(get_db)):
    proof = db.get(InvoicePaymentProof, proof_id)
    if not proof:
        raise HTTPException(404, "Bukti pembayaran tidak ditemukan")
    invoice = db.get(Invoice, proof.invoice_id)
    if not invoice:
        raise HTTPException(404, "Tagihan tidak ditemukan")
    invoice_detail = _invoice_out(db, invoice)
    return {"id": proof.id, "invoice_id": invoice.id, "patient_id": invoice.patient_id,
            "patient_name": invoice_detail["patient_name"], "description": invoice.description,
            "amount": float(proof.amount), "content_type": proof.content_type,
            "image_data_url": f"data:{proof.content_type};base64,{base64.b64encode(proof.data).decode('ascii')}",
            "status": proof.status, "submitted_at": proof.submitted_at.isoformat()}


@app.post("/payment-proofs/{proof_id}/review")
def review_invoice_payment_proof(proof_id: int, body: InvoicePaymentProofReviewIn,
                                 user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    proof = db.scalar(select(InvoicePaymentProof).where(InvoicePaymentProof.id == proof_id).with_for_update())
    if not proof:
        raise HTTPException(404, "Bukti pembayaran tidak ditemukan")
    invoice = db.scalar(select(Invoice).where(Invoice.id == proof.invoice_id).with_for_update())
    if not invoice:
        raise HTTPException(404, "Tagihan tidak ditemukan")
    if proof.status != "pending":
        raise HTTPException(409, "Bukti ini sudah ditinjau admin.")
    if invoice.status == "lunas":
        raise HTTPException(409, "Tagihan ini sudah lunas.")
    reason = body.reason.strip()
    if body.decision == "reject" and not reason:
        raise HTTPException(422, "Alasan penolakan wajib diisi.")
    if body.decision == "approve" and proof.amount != invoice.amount:
        raise HTTPException(409, "Nominal bukti berbeda dari tagihan saat ini; periksa dan perbarui jumlah tagihan lebih dulu.")
    proof.status = "approved" if body.decision == "approve" else "rejected"
    proof.rejection_reason = reason if body.decision == "reject" else ""
    proof.reviewed_by, proof.reviewed_at = user.id, datetime.utcnow()
    if body.decision == "approve":
        invoice.status = "lunas"
    audit.append(db, user.username, user.role, "InvoicePaymentProofReviewed", invoice.patient_id,
                 "approved" if body.decision == "approve" else "rejected",
                 f"bukti tagihan #{invoice.id}" + (f": {reason}" if reason else ""))
    db.commit()
    return {"id": proof.id, "invoice_id": invoice.id, "status": proof.status,
            "invoice_status": invoice.status, "rejection_reason": proof.rejection_reason}


# ---------- perawatan dan jadwal pemeriksaan ----------
def _patient_name(db: Session, patient_id: str) -> str:
    profile = db.get(PatientProfile, patient_id)
    if profile:
        return profile.full_name
    owner = db.scalar(select(User).where(User.patient_id == patient_id))
    user_profile = db.get(UserProfile, owner.id) if owner else None
    return user_profile.full_name if user_profile else "Nama belum diisi"


def _appointment_out(db: Session, item: Appointment) -> dict:
    return {"id": item.id, "patient_id": item.patient_id, "patient_name": _patient_name(db, item.patient_id),
            "scheduled_at": item.scheduled_at.isoformat(), "kind": item.kind, "room": item.room,
            "notes": item.notes, "status": item.status, "created_by": item.created_by}


@app.get("/care")
def list_care(user: User = Depends(current_user), db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    records = [db.get(Record, user.patient_id)] if user.role == "pasien" and user.patient_id else db.scalars(select(Record))
    result = []
    for rec in records:
        if not rec or not _allowed(db, user, rec, "read"):
            continue
        care = db.get(PatientCare, rec.id)
        episode = active_episode(db, rec.id)
        assigned = db.get(User, episode.doctor_id) if episode and episode.doctor_id else None
        assignment = db.get(PatientDoctorAssignment, rec.id)
        assigned = assigned or (db.get(User, assignment.doctor_id) if assignment and assignment.doctor_id else None)
        assigned_profile = db.get(UserProfile, assigned.id) if assigned else None
        result.append({"patient_id": rec.id, "patient_name": _patient_name(db, rec.id),
                       "status": care.status if care else "rawat_jalan", "room": care.room if care else "Belum ditentukan",
                       "note": care.note if care else "", "updated_at": care.updated_at.isoformat() if care else None,
                       "doctor_name": (assigned_profile.full_name if assigned_profile else assigned.username) if assigned else (episode.doctor_name if episode else ""),
                       "specialty": episode.specialty if episode else (assignment.specialty if assignment else "")})
    return result


@app.put("/care/{rid}")
def update_care(rid: str, body: CareUpdateIn, user: User = Depends(require_role("admin", "dokter")),
                db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    if user.role == "dokter" and not _allowed(db, user, rec, "read"):
        raise HTTPException(403, "Dokter tidak memiliki akses ke pasien ini")
    care = db.get(PatientCare, rid) or PatientCare(patient_id=rid, updated_by=user.username)
    previous_status = care.status or "rawat_jalan"
    previous_room = care.room or "Belum ditentukan"
    previous_note = care.note or ""
    episode = active_episode(db, rid)
    if body.status in ("dirawat", "operasi"):
        episode = start_episode(db, rid, rec.diagnosis, rec.history, user.username, body.status)
        assignment = db.get(PatientDoctorAssignment, rid)
        if assignment:
            assignment.doctor_id, assignment.specialty = episode.doctor_id, episode.specialty
        else:
            db.add(PatientDoctorAssignment(patient_id=rid, doctor_id=episode.doctor_id,
                                           specialty=episode.specialty, assigned_by=user.username))
    elif episode and body.status in ("rawat_jalan", "pulang"):
        episode.discharged_at = datetime.utcnow()
        add_activity(db, rid, "keluar", f"Pasien keluar dari rawat inap dengan status {body.status.replace('_', ' ')}.",
                     user.username, episode)
    care.status, care.room, care.note = body.status, body.room, body.note
    care.updated_by, care.updated_at = user.username, datetime.utcnow()
    db.add(care)
    if previous_status != body.status or previous_room != body.room or previous_note != body.note:
        add_activity(db, rid, "perawatan",
                     f"Status perawatan: {previous_status.replace('_', ' ')} → {body.status.replace('_', ' ')}; ruangan {body.room}. "
                     f"{body.note}".strip(), user.username, episode)
    audit.append(db, user.username, user.role, "PatientCareUpdated", rid, "ok", f"{care.status} · {care.room}")
    db.commit()
    process_pending(db, chain)
    doctor = db.get(User, episode.doctor_id) if episode and episode.doctor_id else None
    doctor_profile = db.get(UserProfile, doctor.id) if doctor else None
    return {"patient_id": rid, "status": care.status, "room": care.room, "note": care.note,
            "updated_at": care.updated_at.isoformat(),
            "doctor_name": (doctor_profile.full_name if doctor_profile else doctor.username) if doctor else (episode.doctor_name if episode else ""),
            "specialty": episode.specialty if episode else "",
            "ecg_available": ecg_is_available(db, rid, care.status)}


@app.get("/tracking")
def get_patient_tracking(patient_id: str | None = None,
                         user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    query = select(PatientActivity).order_by(PatientActivity.occurred_at.desc(), PatientActivity.id.desc())
    if patient_id:
        _record(db, patient_id)
        query = query.where(PatientActivity.patient_id == patient_id)
    items = list(db.scalars(query.limit(1000)))
    result = []
    for item in items:
        doctor = db.get(User, item.doctor_id) if item.doctor_id else None
        profile = db.get(UserProfile, doctor.id) if doctor else None
        result.append({"id": item.id, "patient_id": item.patient_id,
                       "patient_name": _patient_name(db, item.patient_id),
                       "activity_type": item.activity_type, "description": item.description,
                       "actor": item.actor, "doctor_name": profile.full_name if profile else (doctor.username if doctor else item.doctor_name),
                       "specialty": item.specialty, "occurred_at": item.occurred_at.isoformat() + "Z"})
    return result


@app.get("/records/{rid}/timeline")
def get_record_timeline(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db),
                        chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "read")
    events, digest = timeline_snapshot(db, rid)
    anchor = db.scalar(select(TimelineAnchor).where(
        TimelineAnchor.patient_id == rid, TimelineAnchor.timeline_hash == digest,
        TimelineAnchor.status == "confirmed"
    ).order_by(TimelineAnchor.id.desc()).limit(1))
    pending = db.scalar(select(TimelineAnchor).where(
        TimelineAnchor.patient_id == rid, TimelineAnchor.timeline_hash == digest,
        TimelineAnchor.status == "pending"
    ).order_by(TimelineAnchor.id.desc()).limit(1))
    intact = audit.verify_chain(db) is None
    info = chain_metadata()
    displayed_events = [{**item, "occurred_at": item["occurred_at"] + "Z"} for item in events]
    return {"patient_id": rid, "events": displayed_events, "fingerprint": digest,
            "audit_chain_intact": intact, "anchor_status": "confirmed" if anchor else "pending" if pending else "unanchored",
            "transaction_hash": anchor.tx_hash if anchor else None, "network": info["network"],
            "explorer_tx_url": f"{info['explorer_tx_base']}{anchor.tx_hash}" if anchor and anchor.tx_hash and info["explorer_tx_base"] else None}


@app.post("/records/{rid}/timeline/anchor")
def anchor_record_timeline(rid: str, user: User = Depends(require_role("admin", "auditor")),
                           db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "read")
    _, digest = timeline_snapshot(db, rid)
    anchor = enqueue_timeline_anchor(db, rid, chain_key(rid), digest, user.username, user.role)
    audit.append(db, user.username, user.role, "TimelineAnchorRequested", rid, "pending", digest)
    db.commit()
    process_pending(db, chain)
    db.refresh(anchor)
    return {"anchor_status": anchor.status, "fingerprint": digest, "transaction_hash": anchor.tx_hash,
            "pending_count": _pending_chain_count(db, rid)}


@app.get("/records/{rid}/observations")
def list_clinical_observations(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db),
                               chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "read")
    observations = list(db.scalars(select(ClinicalObservation).where(
        ClinicalObservation.patient_id == rid
    ).order_by(ClinicalObservation.observed_at.desc()).limit(100)))
    return [{"id": item.id, "heart_rate": item.heart_rate, "spo2": item.spo2,
             "temperature_c": item.temperature_c, "systolic_bp": item.systolic_bp,
             "diastolic_bp": item.diastolic_bp, "note": item.note,
             "observed_at": item.observed_at.isoformat() + "Z"} for item in observations]


@app.post("/records/{rid}/observations", status_code=201)
def create_clinical_observation(rid: str, body: ClinicalObservationIn,
                                user: User = Depends(require_role("dokter")),
                                db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "write")
    values = body.model_dump()
    if not any(values[key] is not None for key in ("heart_rate", "spo2", "temperature_c", "systolic_bp", "diastolic_bp")):
        raise HTTPException(422, "Isi minimal satu parameter observasi")
    observation = ClinicalObservation(patient_id=rid, observed_by=user.id, **values)
    db.add(observation)
    db.flush()
    add_activity(db, rid, "observasi", "Dokter mencatat observasi tanda vital.", user.username, active_episode(db, rid), user)
    audit.append(db, user.username, user.role, "ClinicalObservationRecorded", rid, "ok", f"observasi #{observation.id}")
    db.commit()
    process_pending(db, chain)
    return {"id": observation.id, "observed_at": observation.observed_at.isoformat() + "Z"}


@app.get("/records/{rid}/alerts")
def get_clinical_alerts(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db),
                        chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "read")
    alerts = []
    if rec.diagnosis.strip().casefold() in ("belum ada diagnosis", "belum diisi", "unknown"):
        alerts.append({"id": "diagnosis-missing", "severity": "review", "title": "Diagnosis belum dilengkapi",
                       "reason": "Catatan rekam medis masih memakai nilai awal.", "action": "Dokter penanggung jawab meninjau dan melengkapi diagnosis."})
    episode = active_episode(db, rid)
    if episode:
        has_observation = db.scalar(select(ClinicalObservation.id).where(
            ClinicalObservation.patient_id == rid, ClinicalObservation.observed_at >= episode.admitted_at
        ).limit(1)) is not None
        if not has_observation:
            alerts.append({"id": "vitals-not-recorded", "severity": "review", "title": "Observasi tanda vital belum tercatat",
                           "reason": "Episode rawat inap aktif belum memiliki observasi tanda vital.",
                           "action": "Tinjau kebutuhan pencatatan observasi oleh tenaga klinis."})
    overdue = list(db.scalars(select(Appointment).where(
        Appointment.patient_id == rid, Appointment.status == "terjadwal", Appointment.scheduled_at < datetime.now()
    ).order_by(Appointment.scheduled_at)))
    for appointment in overdue:
        alerts.append({"id": f"appointment-{appointment.id}", "severity": "review", "title": "Jadwal pemeriksaan telah lewat",
                       "reason": f"{appointment.kind} dijadwalkan {appointment.scheduled_at.isoformat()}.",
                       "action": "Konfirmasi hasil kunjungan atau jadwalkan ulang."})
    try:
        integrity = services.check_integrity(db, chain, rec)
        if integrity["status"] != "valid":
            alerts.append({"id": "integrity-review", "severity": "review", "title": "Integritas rekam perlu ditinjau",
                           "reason": f"Status integritas: {integrity['status']}.", "action": "Admin atau auditor meninjau status dan antrean blockchain."})
    except Exception:
        alerts.append({"id": "integrity-unavailable", "severity": "review", "title": "Verifikasi integritas belum tersedia",
                       "reason": "Blockchain atau layanan integritas belum dapat dihubungi.", "action": "Coba lagi setelah layanan tersedia."})
    return {"alerts": alerts, "notice": "Peringatan alur kerja untuk ditinjau tenaga kesehatan; bukan diagnosis atau rekomendasi perawatan."}


def _clinical_item(item) -> dict:
    return {key: (value.isoformat() if isinstance(value, datetime) else value)
            for key, value in vars(item).items() if not key.startswith("_")}


@app.get("/records/{rid}/clinical")
def get_clinical_care(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db),
                      chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "read")
    return {"allergies": [_clinical_item(x) for x in db.scalars(select(PatientAllergy).where(PatientAllergy.patient_id == rid).order_by(PatientAllergy.created_at.desc()))],
            "medications": [_clinical_item(x) for x in db.scalars(select(MedicationOrder).where(MedicationOrder.patient_id == rid).order_by(MedicationOrder.created_at.desc()))],
            "diagnostics": [_clinical_item(x) for x in db.scalars(select(DiagnosticOrder).where(DiagnosticOrder.patient_id == rid).order_by(DiagnosticOrder.ordered_at.desc()))]}


@app.post("/records/{rid}/allergies", status_code=201)
def create_allergy(rid: str, body: AllergyIn, user: User = Depends(require_role("dokter")),
                   db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "write")
    item = PatientAllergy(patient_id=rid, substance=body.substance.strip(), reaction=body.reaction.strip(),
                          severity=body.severity, status=body.status, recorded_by=user.username)
    db.add(item)
    add_activity(db, rid, "alergi", "Dokter memperbarui daftar alergi pasien.", user.username, active_episode(db, rid), user)
    audit.append(db, user.username, user.role, "ALLERGY_RECORDED", rid, "ok")
    db.commit()
    process_pending(db, chain)
    return _clinical_item(item)


@app.put("/records/{rid}/allergies/{allergy_id}")
def update_allergy(rid: str, allergy_id: int, body: AllergyIn, user: User = Depends(require_role("dokter")),
                   db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "write")
    item = db.get(PatientAllergy, allergy_id)
    if not item or item.patient_id != rid:
        raise HTTPException(404, "Catatan alergi tidak ditemukan")
    item.substance, item.reaction, item.severity, item.status = body.substance.strip(), body.reaction.strip(), body.severity, body.status
    add_activity(db, rid, "alergi", "Dokter memperbarui status alergi pasien.", user.username, active_episode(db, rid), user)
    audit.append(db, user.username, user.role, "ALLERGY_UPDATED", rid, "ok")
    db.commit()
    process_pending(db, chain)
    return _clinical_item(item)


@app.post("/records/{rid}/medications", status_code=201)
def create_medication(rid: str, body: MedicationOrderIn, user: User = Depends(require_role("dokter")),
                      db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "write")
    item = MedicationOrder(patient_id=rid, medication=body.medication.strip(), dose=body.dose.strip(),
                           route=body.route.strip(), frequency=body.frequency.strip(), instructions=body.instructions.strip(),
                           prescribed_by=user.username)
    db.add(item)
    add_activity(db, rid, "terapi", "Dokter menambahkan instruksi terapi ke rekam medis.", user.username, active_episode(db, rid), user)
    audit.append(db, user.username, user.role, "MEDICATION_ORDERED", rid, "ok")
    db.commit()
    process_pending(db, chain)
    return _clinical_item(item)


@app.put("/records/{rid}/medications/{order_id}")
def update_medication(rid: str, order_id: int, body: MedicationOrderUpdateIn, user: User = Depends(require_role("dokter")),
                      db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "write")
    item = db.get(MedicationOrder, order_id)
    if not item or item.patient_id != rid:
        raise HTTPException(404, "Instruksi terapi tidak ditemukan")
    item.status = body.status
    item.end_at = datetime.utcnow() if body.status != "active" else None
    add_activity(db, rid, "terapi", "Dokter memperbarui status instruksi terapi.", user.username, active_episode(db, rid), user)
    audit.append(db, user.username, user.role, "MEDICATION_UPDATED", rid, "ok")
    db.commit()
    process_pending(db, chain)
    return _clinical_item(item)


@app.post("/records/{rid}/diagnostics", status_code=201)
def create_diagnostic(rid: str, body: DiagnosticOrderIn, user: User = Depends(require_role("dokter")),
                      db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "write")
    item = DiagnosticOrder(patient_id=rid, kind=body.kind, test_name=body.test_name.strip(),
                           clinical_note=body.clinical_note.strip(), ordered_by=user.username)
    db.add(item)
    add_activity(db, rid, "pemeriksaan", "Dokter membuat permintaan pemeriksaan penunjang.", user.username, active_episode(db, rid), user)
    audit.append(db, user.username, user.role, "DIAGNOSTIC_ORDERED", rid, "ok")
    db.commit()
    process_pending(db, chain)
    return _clinical_item(item)


@app.put("/records/{rid}/diagnostics/{order_id}")
def update_diagnostic(rid: str, order_id: int, body: DiagnosticOrderUpdateIn, user: User = Depends(require_role("dokter")),
                      db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    rec = _record(db, rid)
    _guard(db, chain, user, rec, "write")
    item = db.get(DiagnosticOrder, order_id)
    if not item or item.patient_id != rid:
        raise HTTPException(404, "Permintaan pemeriksaan tidak ditemukan")
    item.status, item.result = body.status, body.result.strip()
    item.resulted_at = datetime.utcnow() if body.status == "completed" else None
    add_activity(db, rid, "hasil_pemeriksaan", "Dokter memperbarui status pemeriksaan penunjang.", user.username, active_episode(db, rid), user)
    audit.append(db, user.username, user.role, "DIAGNOSTIC_UPDATED", rid, "ok")
    db.commit()
    process_pending(db, chain)
    return _clinical_item(item)


@app.get("/appointments")
def list_appointments(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = list(db.scalars(select(Appointment).order_by(Appointment.scheduled_at)))
    if user.role == "pasien":
        items = [x for x in items if x.patient_id == user.patient_id]
    elif user.role == "dokter":
        items = [x for x in items if _allowed(db, user, _record(db, x.patient_id), "read")]
    return [_appointment_out(db, x) for x in items]


@app.post("/appointments", status_code=201)
def create_appointment(body: AppointmentIn, user: User = Depends(require_role("admin", "dokter")),
                       db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    _record(db, body.patient_id)
    if user.role == "dokter" and not _allowed(db, user, _record(db, body.patient_id), "read"):
        raise HTTPException(403, "Dokter tidak memiliki akses ke pasien ini")
    if body.scheduled_at <= datetime.now():
        raise HTTPException(422, "Jadwal harus berada di masa depan")
    item = Appointment(**body.model_dump(), created_by=user.username)
    db.add(item)
    db.flush()
    episode = active_episode(db, body.patient_id)
    add_activity(db, body.patient_id, "pemeriksaan", f"Pemeriksaan dijadwalkan pada {body.scheduled_at.isoformat()}: {body.kind}.",
                 user.username, episode)
    audit.append(db, user.username, user.role, "AppointmentCreated", body.patient_id, "ok", f"jadwal #{item.id}")
    db.commit()
    process_pending(db, chain)
    return _appointment_out(db, item)


@app.put("/appointments/{appointment_id}")
def update_appointment(appointment_id: int, body: AppointmentUpdateIn,
                       user: User = Depends(require_role("admin", "dokter")), db: Session = Depends(get_db),
                       chain: ChainClient = Depends(get_chain)):
    item = db.get(Appointment, appointment_id)
    if not item:
        raise HTTPException(404, "Jadwal tidak ditemukan")
    if user.role == "dokter" and not _allowed(db, user, _record(db, item.patient_id), "read"):
        raise HTTPException(403, "Dokter tidak memiliki akses ke pasien ini")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    add_activity(db, item.patient_id, "pemeriksaan", f"Jadwal pemeriksaan #{item.id} diperbarui.",
                 user.username, active_episode(db, item.patient_id))
    audit.append(db, user.username, user.role, "AppointmentUpdated", item.patient_id, "ok", f"jadwal #{item.id}")
    db.commit()
    process_pending(db, chain)
    return _appointment_out(db, item)


@app.delete("/appointments/{appointment_id}")
def delete_appointment(appointment_id: int, user: User = Depends(require_role("admin", "dokter")),
                       db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    item = db.get(Appointment, appointment_id)
    if not item:
        raise HTTPException(404, "Jadwal tidak ditemukan")
    if user.role == "dokter" and not _allowed(db, user, _record(db, item.patient_id), "read"):
        raise HTTPException(403, "Dokter tidak memiliki akses ke pasien ini")
    patient_id = item.patient_id
    db.delete(item)
    add_activity(db, patient_id, "pemeriksaan", f"Jadwal pemeriksaan #{appointment_id} dibatalkan.",
                 user.username, active_episode(db, patient_id))
    audit.append(db, user.username, user.role, "AppointmentDeleted", patient_id, "ok", f"jadwal #{appointment_id}")
    db.commit()
    process_pending(db, chain)
    return {"deleted": True}


def _request_out(db: Session, item: AppointmentRequest) -> dict:
    return {"id": item.id, "patient_id": item.patient_id, "patient_name": _patient_name(db, item.patient_id),
            "requested_at": item.requested_at.isoformat(), "kind": item.kind, "notes": item.notes,
            "status": item.status, "doctor_approved_by": item.doctor_approved_by,
            "admin_approved_by": item.admin_approved_by, "decision_note": item.decision_note}


@app.get("/appointment-requests")
def list_appointment_requests(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = list(db.scalars(select(AppointmentRequest).order_by(AppointmentRequest.created_at.desc())))
    if user.role == "pasien":
        items = [x for x in items if x.patient_id == user.patient_id]
    elif user.role == "dokter":
        items = [x for x in items if _allowed(db, user, _record(db, x.patient_id), "read")]
    return [_request_out(db, x) for x in items]


@app.post("/appointment-requests", status_code=201)
def create_appointment_request(body: AppointmentRequestIn, user: User = Depends(require_role("pasien")),
                               db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    if not user.patient_id:
        raise HTTPException(409, "Akun pasien belum terhubung ke rekam medis")
    if body.requested_at <= datetime.now():
        raise HTTPException(422, "Tanggal permohonan harus berada di masa depan")
    item = AppointmentRequest(patient_id=user.patient_id, requested_at=body.requested_at,
                              kind=body.kind, notes=body.notes)
    db.add(item)
    db.flush()
    add_activity(db, user.patient_id, "permohonan", f"Pasien mengajukan {item.kind} pada {item.requested_at.isoformat()}.",
                 user.username, active_episode(db, user.patient_id))
    audit.append(db, user.username, user.role, "AppointmentRequested", user.patient_id, "ok", f"permohonan #{item.id}")
    db.commit()
    process_pending(db, chain)
    return _request_out(db, item)


@app.post("/appointment-requests/{request_id}/decision")
def decide_appointment_request(request_id: int, body: AppointmentDecisionIn,
                               user: User = Depends(require_role("admin", "dokter")), db: Session = Depends(get_db),
                               chain: ChainClient = Depends(get_chain)):
    item = db.get(AppointmentRequest, request_id)
    if not item:
        raise HTTPException(404, "Permohonan tidak ditemukan")
    if user.role == "dokter" and not _allowed(db, user, _record(db, item.patient_id), "read"):
        raise HTTPException(403, "Dokter tidak memiliki akses ke pasien ini")
    if item.status in ("disetujui", "ditolak"):
        raise HTTPException(409, "Permohonan sudah diputuskan")
    if body.decision == "tolak":
        item.status = "ditolak"
    else:
        if user.role == "dokter":
            if item.doctor_approved_by:
                # Approval is idempotent: a repeated click must not create a
                # misleading error or overwrite who recorded the approval.
                return _request_out(db, item)
            item.doctor_approved_by = user.username
        else:
            if item.admin_approved_by:
                return _request_out(db, item)
            item.admin_approved_by = user.username
        if item.doctor_approved_by and item.admin_approved_by:
            item.status = "disetujui"
            db.add(Appointment(patient_id=item.patient_id, scheduled_at=item.requested_at, kind=item.kind,
                               room="Poli jantung", notes=item.notes, status="terjadwal", created_by=user.username))
        else:
            item.status = "menunggu_admin" if item.doctor_approved_by else "menunggu_dokter"
    item.decision_note = body.note
    add_activity(db, item.patient_id, "permohonan", f"Permohonan pemeriksaan #{item.id}: {item.status}.",
                 user.username, active_episode(db, item.patient_id))
    if item.status == "disetujui":
        add_activity(db, item.patient_id, "pemeriksaan", f"Jadwal pemeriksaan disetujui untuk {item.requested_at.isoformat()}.",
                     user.username, active_episode(db, item.patient_id))
    audit.append(db, user.username, user.role, "AppointmentRequestDecision", item.patient_id, "ok",
                 f"permohonan #{item.id}: {item.status}")
    db.commit()
    process_pending(db, chain)
    return _request_out(db, item)


# ---------- kontrol akses ----------
@app.get("/records/{rid}/access")
def get_access(rid: str, user: User = Depends(require_role("admin", "auditor")), db: Session = Depends(get_db)):
    _record(db, rid)
    return {r: bool((a := db.get(Access, (rid, r))) and a.allowed) for r in ACL_ROLES}


@app.put("/records/{rid}/access/{role}")
def set_access(rid: str, role: str, body: AccessIn, user: User = Depends(require_role("auditor")),
               db: Session = Depends(get_db), chain: ChainClient = Depends(get_chain)):
    _record(db, rid)
    if role not in ACL_ROLES:
        raise HTTPException(422, "Peran tidak valid")
    row = db.get(Access, (rid, role)) or Access(record_id=rid, role=role)
    row.allowed = body.allowed
    db.add(row)
    enqueue_access(db, rid, chain_key(rid), role_hash(role), body.allowed, user.username, user.role)
    audit.append(db, user.username, user.role, "AccessGranted" if body.allowed else "AccessRevoked",
                 rid, "pending", f"peran {role} menunggu konfirmasi blockchain")
    db.commit()
    process_pending(db, chain)
    return {"role": role, "allowed": body.allowed, "chain_sync_pending": _pending_chain_count(db, rid) > 0}


# ---------- audit trail ----------
@app.get("/audit")
def get_audit(limit: int = 100, user: User = Depends(require_role("admin", "auditor")), db: Session = Depends(get_db)):
    limit = max(1, min(limit, 500))
    return [{"id": r.id, "ts": r.ts, "actor": r.actor, "role": r.role, "action": r.action, "record_id": r.record_id,
             "outcome": r.outcome, "detail": r.detail, "tx_hash": r.tx_hash} for r in reversed(audit.rows(db)[-limit:])]


@app.get("/audit/verify")
def verify_audit(user: User = Depends(require_role("admin", "auditor")), db: Session = Depends(get_db)):
    bad = audit.verify_chain(db)
    return {"intact": bad is None, "first_broken_id": bad}


# ---------- simulasi tampering (hanya dev/demo) ----------
_originals: dict = {}
if settings.enable_tamper_sim:
    @app.post("/dev/tamper/{rid}")
    def tamper(rid: str, body: TamperIn, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
        rec = _record(db, rid)
        _originals.setdefault(rid, {"diagnosis": rec.diagnosis, "notes": rec.notes, "samples": db.get(Biosignal, rid).samples})
        if body.target == "diagnosis":
            rec.diagnosis = "Tidak ada kelainan jantung"
        elif body.target == "notes":
            rec.notes = "Obat dihentikan. Tidak perlu kontrol ulang."
        else:
            b = db.get(Biosignal, rid)
            s = json.loads(b.samples)
            for i in range(min(500, len(s) - 1), min(520, len(s))):
                s[i] = 1.5
            b.samples = json.dumps(s)
        audit.append(db, user.username, user.role, "TAMPER_SIM", rid, "ok", f"DB diubah langsung: {body.target}")
        db.commit()
        return {"changed": body.target, "note": "Smart contract tidak berubah; jalankan verifikasi untuk melihat deteksinya."}

    @app.post("/dev/restore/{rid}")
    def restore(rid: str, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
        rec, snap = _record(db, rid), _originals.get(rid)
        if not snap:
            raise HTTPException(404, "Tidak ada data asli yang tersimpan")
        rec.diagnosis, rec.notes = snap["diagnosis"], snap["notes"]
        db.get(Biosignal, rid).samples = snap["samples"]
        _originals.pop(rid)
        audit.append(db, user.username, user.role, "RESTORE_SIM", rid, "ok", "data demo dipulihkan")
        db.commit()
        return {"restored": True}


# ---------- antarmuka web (satu proses, satu origin) ----------
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/app/")


if FRONT.exists():
    app.mount("/app", StaticFiles(directory=FRONT, html=True), name="frontend")
