"""Idempotently add synthetic specialist and patient accounts to the dev database."""
from datetime import date, datetime
import os
import secrets

from sqlalchemy import select

from app import services
from app.chain import get_chain
from app.chain_ops import enqueue_access, process_pending
from app.clinical import add_activity, choose_doctor, ensure_patient_doctor_assignments, start_episode
from app.db import (Access, DoctorSpecialty, PatientCare, PatientDoctorAssignment,
                    PatientProfile, SessionLocal, User, UserProfile, init_db)
from app.hashing import chain_key, role_hash
from app.security import hash_password
from app.schemas import RecordIn
from app.usernames import simple_username


DOCTORS = [
    ("Bima Setiawan", "Jantung", date(1978, 5, 12)),
    ("Maya Putri", "Bedah", date(1984, 8, 23)),
    ("Rafi Nugraha", "Saraf", date(1982, 11, 4)),
    ("Sinta Maharani", "Penyakit Dalam", date(1979, 2, 16)),
    ("Fajar Prakoso", "Anak", date(1985, 7, 9)),
    ("Citra Anindya", "Ortopedi", date(1983, 1, 27)),
]

PATIENTS = [
    ("Abrar Arrazzaq", date(2004, 6, 14), "L", "Aritmia jantung", "dirawat", "ICU Jantung 02"),
    ("Salsabila Putri", date(1997, 3, 2), "P", "Apendisitis akut pasca operasi", "pemulihan", "Ruang Bedah 204"),
    ("Reza Pratama", date(1990, 10, 7), "L", "Stroke iskemik", "dirawat", "Neurologi 301"),
    ("Nabila Zahra", date(1988, 9, 29), "P", "Diabetes tipe 2", "rawat_jalan", "Poli Penyakit Dalam"),
    ("Dimas Saputra", date(1983, 4, 18), "L", "Fraktur tulang lengan pasca operasi", "pulang", "Ortopedi 112"),
    ("Alya Permata", date(2018, 12, 5), "P", "Demam berdarah dengue pada anak", "dirawat", "Ruang Anak 105"),
]


def credentials(name: str) -> tuple[str, str]:
    # Use the operator-configured dev password, or an unlogged random secret.
    # Never derive credentials from synthetic demographic fields.
    return simple_username(name), os.getenv("SEED_PASSWORD") or secrets.token_urlsafe(24)


def main() -> None:
    init_db()
    chain = get_chain()
    created_accounts = []
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.role == "admin").order_by(User.id))
        if admin is None:
            admin_password = os.getenv("SEED_PASSWORD")
            if not admin_password:
                raise SystemExit("Set SEED_PASSWORD before creating the first demo admin account.")
            admin = User(username="admin1", password_hash=hash_password(admin_password), role="admin")
            db.add(admin)
            db.flush()
            db.add(UserProfile(user_id=admin.id, full_name="Nadia Pratama"))
            created_accounts.append(("Admin", admin.username, "Administrasi"))

        for full_name, specialty, birth_date in DOCTORS:
            username, password = credentials(full_name)
            doctor = db.scalar(select(User).where(User.username == username))
            if doctor is None:
                doctor = db.scalar(select(User).join(UserProfile, UserProfile.user_id == User.id).where(
                    User.role == "dokter", UserProfile.full_name == f"Dr. {full_name}"))
                if doctor:
                    doctor.username = username
            profile = None
            if doctor is None:
                doctor = User(username=username, password_hash=hash_password(password), role="dokter")
                db.add(doctor)
                db.flush()
                profile = UserProfile(user_id=doctor.id, full_name=f"Dr. {full_name}", birth_date=birth_date)
                db.add(profile)
                created_accounts.append(("Dokter", username, specialty))
            else:
                profile = db.get(UserProfile, doctor.id)
                if profile:
                    profile.full_name = f"Dr. {full_name}"
                    profile.birth_date = birth_date
            spec = db.get(DoctorSpecialty, doctor.id)
            if spec:
                spec.specialty = specialty
            else:
                db.add(DoctorSpecialty(user_id=doctor.id, specialty=specialty))

        # Make specialties added above visible to db.get before filling defaults.
        db.flush()
        for doctor in db.scalars(select(User).where(User.role == "dokter")):
            if not db.get(DoctorSpecialty, doctor.id):
                db.add(DoctorSpecialty(user_id=doctor.id, specialty="Penyakit Dalam"))

        db.flush()
        for full_name, birth_date, sex, diagnosis, status, room in PATIENTS:
            username, password = credentials(full_name)
            patient_user = db.scalar(select(User).where(User.username == username))
            if patient_user is None:
                patient_user = db.scalar(select(User).join(
                    PatientProfile, PatientProfile.record_id == User.patient_id
                ).where(User.role == "pasien", PatientProfile.full_name == full_name))
                if patient_user:
                    patient_user.username = username
            if patient_user:
                continue
            age = date.today().year - birth_date.year - ((date.today().month, date.today().day) < (birth_date.month, birth_date.day))
            user = User(username=username, password_hash=hash_password(password), role="pasien")
            db.add(user)
            db.flush()
            db.add(UserProfile(user_id=user.id, full_name=full_name, birth_date=birth_date, sex=sex))
            db.flush()
            rec = services.create_record(db, chain, admin, RecordIn(
                age=age, sex=sex, history=f"Riwayat demo sintetis terkait {diagnosis.lower()}.",
                diagnosis=diagnosis, notes="Data contoh sintetis untuk demonstrasi MediChain.",
                ecg={"fs": 250, "samples": services.make_patient_ecg(user.id * 7919)}
            ))
            user.patient_id = rec.id
            db.add(PatientProfile(record_id=rec.id, full_name=full_name, birth_date=birth_date, sex=sex))
            access = db.get(Access, (rec.id, "pasien"))
            access.allowed = True
            enqueue_access(db, rec.id, chain_key(rec.id), role_hash("pasien"), True,
                           admin.username, admin.role)
            db.add(PatientCare(patient_id=rec.id, status=status, room=room, note="", updated_by=admin.username))
            add_activity(db, rec.id, "registrasi", "Akun pasien dan rekam medis demo dibuat.", admin.username)
            if status in ("dirawat", "operasi", "pemulihan", "pulang"):
                episode = start_episode(db, rec.id, diagnosis, rec.history, admin.username,
                                        "operasi" if "operasi" in diagnosis.casefold() else "dirawat")
                assigned_doctor_id, specialty = episode.doctor_id, episode.specialty
                if status == "pulang":
                    episode.discharged_at = datetime.utcnow()
                    add_activity(db, rec.id, "keluar", "Pasien keluar dari rumah sakit.", admin.username, episode)
            else:
                doctor, specialty = choose_doctor(db, diagnosis, rec.history)
                assigned_doctor_id = doctor.id
            db.add(PatientDoctorAssignment(patient_id=rec.id, doctor_id=assigned_doctor_id,
                                           specialty=specialty, assigned_by=admin.username))
            created_accounts.append(("Pasien", username, diagnosis))
        # Persist pending assignments in the session identity map before backfilling.
        db.flush()
        ensure_patient_doctor_assignments(db, admin.username)
        db.commit()
        process_pending(db, chain)

    print("Akun demo ditambahkan (data pasien seluruhnya sintetis):")
    for kind, username, detail in created_accounts:
        print(f"{kind} | {username} | {detail}")
    if not created_accounts:
        print("Semua akun contoh sudah ada; tidak ada perubahan akun.")
    print("Password tidak ditampilkan. Gunakan SEED_PASSWORD yang dikonfigurasi operator atau reset password akun demo melalui admin.")


if __name__ == "__main__":
    main()
