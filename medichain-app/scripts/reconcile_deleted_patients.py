"""Remove off-chain records left behind by the old patient-account delete flow.

Dry-run by default. The script only touches records referenced by a UserDeleted
audit event and with no remaining patient account.
"""
import argparse

from sqlalchemy import delete, select

from app import audit
from app.chain import get_chain
from app.chain_ops import process_pending
from app.db import DoctorSpecialty, SessionLocal, User, UserProfile, init_db
from app.retention import erase_patient_record, orphaned_deleted_patient_ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="erase matching off-chain patient records")
    args = parser.parse_args()

    init_db()
    chain = get_chain()
    with SessionLocal() as db:
        broken_audit_id = audit.verify_chain(db)
        if broken_audit_id is not None:
            raise SystemExit(f"Audit trail tidak utuh pada baris {broken_audit_id}; cleanup dibatalkan.")
        record_ids = orphaned_deleted_patient_ids(db)
        print(f"Ditemukan {len(record_ids)} rekam tanpa akun pasien yang memiliki jejak UserDeleted.")
        if not args.execute:
            print("Mode pratinjau. Jalankan ulang dengan --execute untuk menghapus data off-chain terkait.")
            return
        for record_id in record_ids:
            erase_patient_record(db, chain, record_id, "system-maintenance", "system")
            db.commit()
        orphan_user_ids = select(User.id)
        deleted_profiles = db.execute(delete(UserProfile).where(~UserProfile.user_id.in_(orphan_user_ids))).rowcount or 0
        deleted_specialties = db.execute(delete(DoctorSpecialty).where(~DoctorSpecialty.user_id.in_(orphan_user_ids))).rowcount or 0
        if deleted_profiles or deleted_specialties:
            audit.append(db, "system-maintenance", "system", "OrphanAccountDataErased", None, "ok",
                         f"profil={deleted_profiles}; spesialisasi={deleted_specialties}")
            db.commit()
        print(f"Selesai menghapus {len(record_ids)} rekam dan data turunannya dari database.")
        print(f"Data akun yatim dibersihkan: profil={deleted_profiles}, spesialisasi={deleted_specialties}.")
        print("Jejak audit dan entri blockchain historis tetap tersimpan; akses aktif dicabut bila tersedia.")
        process_pending(db, chain)


if __name__ == "__main__":
    main()
