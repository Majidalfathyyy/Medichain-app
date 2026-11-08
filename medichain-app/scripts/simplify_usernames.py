"""Rename prefixed demo accounts to readable usernames without changing passwords.

Run ``python -m scripts.simplify_usernames`` to preview, or add ``--execute``
to commit the username-only changes to the configured database.
"""
import argparse

from sqlalchemy import select

from app.db import PatientProfile, SessionLocal, User, UserProfile
from app.usernames import simple_username


def plan_changes(db):
    users = list(db.scalars(select(User).order_by(User.id)))
    prefixed = [user for user in users if user.username.upper().startswith(("DR-", "PSN-"))]
    reserved = {user.username.casefold() for user in users if user not in prefixed}
    changes = []
    for user in prefixed:
        profile = db.get(UserProfile, user.id)
        full_name = profile.full_name if profile else ""
        if user.role == "pasien" and user.patient_id:
            patient = db.get(PatientProfile, user.patient_id)
            full_name = patient.full_name if patient else full_name
        target = simple_username(full_name)
        if len(target) < 3:
            raise ValueError(f"Nama profil akun {user.id} tidak menghasilkan username yang valid.")
        base, suffix = target[:37], 1
        target = base
        while target.casefold() in reserved:
            suffix += 1
            tail = f".{suffix}"
            target = f"{base[:40-len(tail)]}{tail}"
        reserved.add(target.casefold())
        changes.append((user, target))
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Simpan perubahan username ke database")
    args = parser.parse_args()
    with SessionLocal() as db:
        changes = plan_changes(db)
        for user, target in changes:
            print(f"{user.role}: {user.username} -> {target}")
            if args.execute:
                user.username = target
        if args.execute:
            db.commit()
            print(f"Selesai. {len(changes)} username diperbarui; password dan data lain tidak diubah.")
        else:
            print(f"Pratinjau saja: {len(changes)} akun. Jalankan ulang dengan --execute untuk menyimpan.")


if __name__ == "__main__":
    main()
