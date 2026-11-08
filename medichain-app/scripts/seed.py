"""Create staff login accounts on a fresh database; patient records are created in the app."""
import os

from sqlalchemy import select

from app.db import SessionLocal, User, UserProfile, init_db
from app.security import hash_password


STAFF = {
    "admin": ("admin1", "Nadia Pratama"),
    "dokter": ("dokter1", "Dr. Bima Setiawan"),
    "auditor": ("auditor1", "Rina Wulandari"),
}


def main() -> None:
    init_db()
    password = os.getenv("SEED_PASSWORD")
    if not password:
        raise SystemExit("Set SEED_PASSWORD in the local environment before creating demo staff accounts.")
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)):
            print("Database sudah berisi akun; seed dibatalkan.")
            return
        for role, (username, full_name) in STAFF.items():
            user = User(username=username, password_hash=hash_password(password), role=role)
            db.add(user)
            db.flush()
            db.add(UserProfile(user_id=user.id, full_name=full_name))
        db.commit()
    print("Akun staf siap: admin1, dokter1, auditor1. Password tidak ditampilkan; gunakan nilai SEED_PASSWORD yang dikonfigurasi operator.")
    print("Tidak ada pasien demo yang dibuat. Tambahkan pasien melalui menu Pengguna.")


if __name__ == "__main__":
    main()
