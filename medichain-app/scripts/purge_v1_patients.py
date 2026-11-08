"""Preview or purge patient records from the explicitly configured Version 1 database.

Run without flags first to inspect the target. Add --execute only after confirming
that DATABASE_URL points at the Version 1 database whose patient data should be removed.
"""
import argparse
from pathlib import Path

from sqlalchemy import inspect, select

from app.config import settings
from app.db import (Access, Appointment, AppointmentRequest, Biosignal, Invoice, PatientCare,
                    PatientProfile, Record, SessionLocal, User, UserProfile)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="permanently remove V1 patient data")
    args = parser.parse_args()

    url = settings.database_url
    if url.startswith("sqlite"):
        db_path = Path(url.removeprefix("sqlite:///"))
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        if not db_path.exists():
            print(f"Database SQLite tidak ditemukan: {db_path}")
            return
        target = f"SQLite {db_path}"
    else:
        parsed = settings.database_url.split("@")[-1]
        target = f"Database {parsed}"

    with SessionLocal() as db:
        inspector = inspect(db.get_bind())
        if "records" not in inspector.get_table_names():
            print(f"Tidak ada tabel pasien pada {target}.")
            return
        ids = list(db.scalars(select(Record.id)))
        account_count = 0
        if ids:
            account_count = len(list(db.scalars(select(User.id).where(User.patient_id.in_(ids)))))
        print(f"Target: {target}")
        print(f"Rekam pasien: {len(ids)} | akun terkait: {account_count}")
        if not args.execute:
            print("Mode pratinjau. Periksa target DATABASE_URL, lalu jalankan ulang dengan --execute untuk menghapus.")
            return
        if not ids:
            print("Tidak ada data pasien untuk dihapus.")
            return

        id_set = set(ids)
        linked_users = list(db.scalars(select(User).where(User.patient_id.in_(id_set))))
        for user in linked_users:
            profile = db.get(UserProfile, user.id)
            if profile:
                db.delete(profile)
            db.delete(user)
        for model in (AppointmentRequest, Appointment, PatientCare, Invoice, Access, Biosignal, PatientProfile):
            if model.__tablename__ in inspector.get_table_names():
                db.query(model).filter(model.patient_id.in_(id_set) if model is not PatientProfile else model.record_id.in_(id_set)).delete(synchronize_session=False)
        db.query(Record).filter(Record.id.in_(id_set)).delete(synchronize_session=False)
        db.commit()
        print(f"Dihapus {len(ids)} rekam pasien beserta profil, akun terkait, tagihan, status perawatan, dan jadwal.")
        print("Audit trail dan catatan blockchain yang immutable tetap ada; database tidak dapat menghapus histori dari blockchain.")


if __name__ == "__main__":
    main()
