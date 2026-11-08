"""Uji alur API dengan SQLite sementara + MockChain; lihat tests/conftest.py."""

from datetime import datetime, timedelta
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select, func  # noqa: E402
from uuid import uuid4  # noqa: E402

from app.db import (Appointment, AppointmentRequest, AuditLog, PatientDoctorAssignment,
                    PatientProfile, Record, SessionLocal, User, UserProfile)  # noqa: E402
from app.main import app, public_registration_limiter  # noqa: E402
from app.security import hash_password  # noqa: E402
from scripts import seed, seed_demo_clinic  # noqa: E402

PW = "Demo-Medichain-2026"


def _login(c, u, password=PW):
    r = c.post("/auth/login", json={"username": u, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_full_flow():
    with TestClient(app) as c:
        seed.main()
        seed_demo_clinic.main()
        dok = _login(c, "bima.setiawan")
        adm = _login(c, "admin1")
        pas = _login(c, "abrar.arrazzaq")
        aud = _login(c, "auditor1")
        records = c.get("/records", headers=adm).json()
        assert len(records) == 6
        rid = next(r["id"] for r in records if r["patient_name"] == "Abrar Arrazzaq")
        other = next(r["id"] for r in records if r["patient_name"] != "Abrar Arrazzaq")

        # Exercise exports through the authenticated API using only synthetic fixtures.
        fhir = c.get(f"/records/{rid}/fhir?scope=full", headers=adm)
        assert fhir.status_code == 200
        assert fhir.headers["content-type"].startswith("application/fhir+json")
        assert fhir.json()["resourceType"] == "Bundle"
        assert fhir.json()["entry"]
        pdf = c.get(f"/records/{rid}/diagnosis.pdf", headers=adm)
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF-")

        assert c.get("/records").status_code == 401
        assert c.get(f"/records/{other}", headers=pas).status_code == 403
        assert c.get(f"/records/{rid}", headers=pas).status_code == 200
        assert c.put(f"/records/{rid}", headers=pas, json={"notes": "x"}).status_code == 403
        assert c.post(f"/records/{rid}/verify", headers=dok).status_code == 403
        assert c.post(f"/records/{rid}/verify", headers=adm).json()["status"] == "valid"
        updated = c.put(f"/records/{rid}", headers=dok, json={"notes": "Catatan baru"})
        assert updated.status_code == 200 and updated.json()["version"] == 2
        assert c.post(f"/records/{rid}/verify", headers=aud).json()["status"] == "valid"

        assert c.post(f"/dev/tamper/{rid}", headers=adm, json={"target": "diagnosis"}).status_code == 200
        v = c.post(f"/records/{rid}/verify", headers=adm).json()
        assert v["status"] == "modified" and not v["record_ok"] and v["ecg_ok"]
        assert c.put(f"/records/{rid}", headers=dok, json={"notes": "cuci"}).status_code == 409

        invoice = c.post("/invoices", headers=adm, json={
            "patient_id": rid, "description": "Tagihan demo", "amount": 125000,
            "due_date": "2026-12-01",
        })
        assert invoice.status_code == 201, invoice.text
        assert invoice.json()["id"] in [i["id"] for i in c.get("/invoices", headers=pas).json()]
        assert c.get("/audit", headers=pas).status_code == 403
        assert c.get("/audit/verify", headers=aud).json()["intact"] is True


def test_appointment_request_requires_both_roles_and_duplicate_approval_is_safe():
    with TestClient(app) as c:
        seed.main()
        seed_demo_clinic.main()
        with SessionLocal() as db:
            assignment = db.scalar(select(PatientDoctorAssignment).where(
                PatientDoctorAssignment.doctor_id.is_not(None)
            ).order_by(PatientDoctorAssignment.patient_id).limit(1))
            assert assignment is not None
            doctor = db.get(User, assignment.doctor_id)
            assert doctor is not None
            request = AppointmentRequest(
                patient_id=assignment.patient_id,
                requested_at=datetime.now() + timedelta(days=7),
                kind="Pemeriksaan lanjutan",
                notes="Permohonan sintetis untuk tes persetujuan.",
            )
            db.add(request)
            db.commit()
            request_id = request.id
            patient_id = request.patient_id
            doctor_username = doctor.username
            appointments_before = db.scalar(select(func.count()).select_from(Appointment)) or 0

        admin = _login(c, "admin1")
        admin_approval = c.post(f"/appointment-requests/{request_id}/decision", headers=admin,
                                json={"decision": "setujui"})
        assert admin_approval.status_code == 200, admin_approval.text
        assert admin_approval.json()["status"] == "menunggu_dokter"
        assert admin_approval.json()["admin_approved_by"] == "admin1"

        # A stale/repeated admin click is idempotent and does not claim completion.
        repeated = c.post(f"/appointment-requests/{request_id}/decision", headers=admin,
                          json={"decision": "setujui"})
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["status"] == "menunggu_dokter"

        doctor_auth = _login(c, doctor_username)
        doctor_approval = c.post(f"/appointment-requests/{request_id}/decision", headers=doctor_auth,
                                 json={"decision": "setujui"})
        assert doctor_approval.status_code == 200, doctor_approval.text
        assert doctor_approval.json()["status"] == "disetujui"
        assert doctor_approval.json()["doctor_approved_by"] == doctor_username
        with SessionLocal() as db:
            assert (db.scalar(select(func.count()).select_from(Appointment)) or 0) == appointments_before + 1
            assert db.scalar(select(Appointment).where(
                Appointment.patient_id == patient_id,
                Appointment.kind == "Pemeriksaan lanjutan",
            )) is not None


def test_login_lockout():
    with TestClient(app) as c:
        for _ in range(5):
            assert c.post("/auth/login", json={"username": "bima.setiawan", "password": "salah-salah"}).status_code == 401
        assert c.post("/auth/login", json={"username": "bima.setiawan", "password": "BimaSetiawan1205"}).status_code == 401  # terkunci


def test_pendaftaran_email_otp_sementara_dinonaktifkan():
    with TestClient(app) as c:
        start = c.post("/auth/register/start", json={
            "full_name": "Pasien Demo",
            "email": "pasien.demo@example.test",
            "password": "Password-demo-2026",
            "birth_date": "1990-01-01",
            "sex": "L",
        })
        verify = c.post("/auth/register/verify", json={
            "challenge_id": "00000000-0000-0000-0000-000000000000",
            "otp": "123456",
        })
        assert start.status_code == 410
        assert verify.status_code == 410


def _registration_data(suffix=None):
    suffix = suffix or uuid4().hex[:10]
    return {
        "full_name": "Pasien Pendaftaran",
        "username": f"signup.{suffix}",
        "email": f"signup.{suffix}@example.test",
        "password": "PasienAman2026",
        "confirm_password": "PasienAman2026",
        "birth_date": "1990-01-01",
        "sex": "P",
    }


def _ensure_admin():
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin1"))
        if not admin:
            admin = User(username="admin1", password_hash=hash_password(PW), role="admin")
            db.add(admin)
            db.flush()
            db.add(UserProfile(user_id=admin.id, full_name="Admin Pengujian"))
            db.commit()


def test_public_patient_registration_waits_for_approval_and_creates_no_record():
    public_registration_limiter.hits.clear()
    with TestClient(app) as c:
        with SessionLocal() as db:
            before = db.scalar(select(func.count()).select_from(Record))
        response = c.post("/auth/register", json=_registration_data())
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "menunggu_persetujuan"
        username = response.json()["username"]
        with SessionLocal() as db:
            patient = db.scalar(select(User).where(User.username == username))
            assert patient and patient.role == "pasien" and not patient.is_active
            assert patient.patient_id is None
            assert db.scalar(select(func.count()).select_from(Record)) == before
        login = c.post("/auth/login", json={"username": username, "password": "PasienAman2026"})
        assert login.status_code == 403
        assert "menunggu persetujuan" in login.json()["detail"].lower()
        assert "access_token" not in login.json()


def test_public_registration_rejects_duplicate_username_and_email_case_insensitively():
    public_registration_limiter.hits.clear()
    with TestClient(app) as c:
        original = _registration_data()
        assert c.post("/auth/register", json=original).status_code == 202
        same_username = {**_registration_data(), "username": original["username"].upper()}
        assert c.post("/auth/register", json=same_username).status_code == 409
        same_email = {**_registration_data(), "email": original["email"].upper()}
        assert c.post("/auth/register", json=same_email).status_code == 409


def test_public_registration_rejects_invalid_input_and_staff_role_attempt():
    public_registration_limiter.hits.clear()
    with TestClient(app) as c:
        body = _registration_data()
        mismatch = c.post("/auth/register", json={**body, "confirm_password": "PasswordBeda2026"})
        assert mismatch.status_code == 422
        assert "PasienAman2026" not in mismatch.text and "PasswordBeda2026" not in mismatch.text
        assert c.post("/auth/register", json={**body, "password": "short", "confirm_password": "short"}).status_code == 422
        assert c.post("/auth/register", json={**body, "role": "admin"}).status_code == 422
        assert c.post("/auth/register", json={**body, "username": "spasi tidak valid"}).status_code == 422


def test_admin_approval_creates_one_record_and_audits_activation():
    public_registration_limiter.hits.clear()
    with TestClient(app) as c:
        _ensure_admin()
        body = _registration_data()
        response = c.post("/auth/register", json=body)
        assert response.status_code == 202, response.text
        with SessionLocal() as db:
            patient = db.scalar(select(User).where(User.username == body["username"]))
            patient_user_id = patient.id
            before = db.scalar(select(func.count()).select_from(Record))
        admin = _login(c, "admin1")
        assert c.post(f"/users/{patient_user_id}/approve").status_code == 401
        bypass = c.put(f"/users/{patient_user_id}", headers=admin,
                       json={"role": "admin", "is_active": True})
        assert bypass.status_code == 422
        approved = c.post(f"/users/{patient_user_id}/approve", headers=admin)
        assert approved.status_code == 200, approved.text
        assert approved.json()["is_active"] is True
        assert approved.json()["patient_id"]
        with SessionLocal() as db:
            patient = db.get(User, patient_user_id)
            assert patient.is_active and patient.patient_id
            assert db.scalar(select(func.count()).select_from(Record)) == before + 1
            assert db.get(PatientProfile, patient.patient_id)
            assert db.scalar(select(AuditLog).where(
                AuditLog.action == "PatientAccountActivated", AuditLog.actor == "admin1",
                AuditLog.record_id == patient.patient_id))
        assert c.post(f"/users/{patient_user_id}/approve", headers=admin).status_code == 409
        patient_auth = _login(c, body["username"], body["password"])
        records = c.get("/records", headers=patient_auth)
        assert records.status_code == 200 and len(records.json()) == 1

        # Deleting the account removes its off-chain record/profile and keeps
        # the immutable audit tombstone.
        patient_id = records.json()[0]["id"]
        deleted = c.delete(f"/users/{patient_user_id}", headers=admin)
        assert deleted.status_code == 200, deleted.text
        with SessionLocal() as db:
            assert db.get(Record, patient_id) is None
            assert db.get(PatientProfile, patient_id) is None
            assert db.get(UserProfile, patient_user_id) is None
            assert db.scalar(select(AuditLog).where(
                AuditLog.action == "UserDeleted", AuditLog.record_id == patient_id))


def test_public_registration_is_rate_limited():
    public_registration_limiter.hits.clear()
    with TestClient(app) as c:
        results = [c.post("/auth/register", json=_registration_data()).status_code for _ in range(5)]
        assert results == [202, 202, 202, 202, 429]
