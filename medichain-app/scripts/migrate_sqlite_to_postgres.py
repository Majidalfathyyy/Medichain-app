"""Copy every MediChain SQLAlchemy table from the legacy SQLite DB to PostgreSQL.

The SQLite source is opened read-only. PostgreSQL is never truncated or dropped.
By default the destination must be empty; --merge opts into primary-key upserts.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import OperationalError

# Make `python scripts/migrate_sqlite_to_postgres.py` work from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.db import AuditLog, Base, SessionLocal
from app.hashing import verify_audit_rows
from app import audit


def _sqlite_value(value, column):
    """Convert SQLite's dynamically typed values to PostgreSQL-friendly Python types."""
    if value is None:
        return None
    kind = column.type
    if isinstance(kind, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(kind, Date) and isinstance(value, str):
        return date.fromisoformat(value)
    if isinstance(kind, Boolean):
        return bool(value)
    if isinstance(kind, Numeric) and not isinstance(value, Decimal):
        return Decimal(str(value))
    if isinstance(kind, Integer):
        return int(value)
    return value


def _source_audit_chain(sqlite_db: sqlite3.Connection, source_tables: set[str]) -> tuple[int, str | None]:
    if "audit_log" not in source_tables:
        return 0, None
    fields = ("ts", "actor", "role", "action", "record_id", "outcome", "detail", "tx_hash")
    rows = [dict(row) for row in sqlite_db.execute(
        "SELECT id, prev_hash, hash, " + ", ".join(fields) + ' FROM "audit_log" ORDER BY id')]
    broken = verify_audit_rows(rows)
    if broken is not None:
        raise SystemExit(f"Audit SQLite tidak utuh pada baris {broken}; migrasi dibatalkan.")
    return len(rows), rows[-1]["hash"] if rows else None


def migrate(source: Path, merge: bool = False, preserve_existing: bool = False) -> None:
    if not source.is_file():
        raise SystemExit(f"Database SQLite tidak ditemukan: {source}")
    if not settings.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise SystemExit("DATABASE_URL harus menunjuk ke PostgreSQL sebagai tujuan migrasi.")

    # Prevent accidental writes to or creation of a SQLite source file.
    source_uri = f"file:{source.resolve().as_posix()}?mode=ro"
    sqlite_db = sqlite3.connect(source_uri, uri=True)
    sqlite_db.row_factory = sqlite3.Row
    sqlite_db.execute("PRAGMA query_only=ON")
    sqlite_db.execute("BEGIN")
    print("SQLite sumber siap dibaca.", flush=True)

    target = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        try:
            print("Menyiapkan schema PostgreSQL...", flush=True)
            Base.metadata.create_all(target)
            print("Schema PostgreSQL siap.", flush=True)
        except OperationalError:
            raise SystemExit(
                "Tidak bisa terhubung ke PostgreSQL. Periksa host, port, nama database, "
                "dan kredensial DATABASE_URL di .env. Tidak ada data yang dipindahkan."
            ) from None
        source_tables = {row[0] for row in sqlite_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        source_audit_count, source_audit_hash = _source_audit_chain(sqlite_db, source_tables)
        tables = list(Base.metadata.sorted_tables)

        with target.connect() as connection:
            print("Memeriksa isi PostgreSQL tujuan...", flush=True)
            populated = {}
            for table in tables:
                count = connection.execute(select(func.count()).select_from(table)).scalar_one()
                if count:
                    populated[table.name] = count
        if populated and not (merge or preserve_existing):
            counts = ", ".join(f"{name}={count}" for name, count in sorted(populated.items()))
            raise SystemExit(
                "PostgreSQL tujuan sudah berisi data (" + counts + "). "
                "Tidak ada baris yang diubah. Backup PostgreSQL dahulu; gunakan --merge hanya "
                "bila nilai SQLite boleh menggantikan baris dengan primary key yang sama."
            )

        copied = {}
        print("Menyalin tabel dari SQLite...", flush=True)
        with target.begin() as connection:
            preserve_audit_history = preserve_existing and populated.get("audit_log", 0) > 0
            for table in tables:
                if table.name not in source_tables:
                    continue
                if table.name == "audit_log" and preserve_audit_history:
                    copied[table.name] = 0
                    print(f"  {table.name}: dilewati; audit PostgreSQL dipertahankan dan audit SQLite tetap di sumber", flush=True)
                    continue
                source_columns = {column[1] for column in sqlite_db.execute(
                    f'PRAGMA table_info("{table.name.replace(chr(34), chr(34) * 2)}")')}
                columns = [column for column in table.columns if column.name in source_columns]
                if not columns:
                    continue
                primary_key = list(table.primary_key.columns)
                if any(column.name not in source_columns for column in primary_key):
                    raise RuntimeError(f"Kolom primary key tabel {table.name} tidak lengkap di SQLite.")

                quoted_table = '"' + table.name.replace('"', '""') + '"'
                selected_columns = ", ".join('"' + col.name.replace('"', '""') + '"' for col in columns)
                rows = sqlite_db.execute(f"SELECT {selected_columns} FROM {quoted_table}").fetchall()
                if not rows:
                    copied[table.name] = 0
                    continue

                mapped = [
                    {column.name: _sqlite_value(row[column.name], column) for column in columns}
                    for row in rows
                ]
                statement = pg_insert(table)
                if preserve_existing:
                    statement = statement.on_conflict_do_nothing()
                elif merge:
                    non_key_columns = [column.name for column in columns
                                       if column.name not in {key.name for key in primary_key}]
                    if non_key_columns:
                        statement = statement.on_conflict_do_update(
                            index_elements=primary_key,
                            set_={name: getattr(statement.excluded, name) for name in non_key_columns},
                        )
                    else:
                        statement = statement.on_conflict_do_nothing(index_elements=primary_key)
                result = connection.execute(statement, mapped)
                copied[table.name] = (max(0, result.rowcount) if preserve_existing else len(mapped))
                label = "baris baru" if preserve_existing else "baris"
                print(f"  {table.name}: {copied[table.name]} {label}", flush=True)

            # Explicit SQLite integer IDs should not leave PostgreSQL sequences behind.
            for table in tables:
                if len(table.primary_key.columns) != 1:
                    continue
                key = next(iter(table.primary_key.columns))
                if not isinstance(key.type, Integer) or key.autoincrement is False:
                    continue
                sequence = connection.execute(text(
                    "SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                    {"table_name": table.name, "column_name": key.name},
                ).scalar_one_or_none()
                maximum = connection.execute(select(func.max(key))).scalar_one_or_none()
                if sequence and maximum is not None:
                    connection.execute(text("SELECT setval(CAST(:sequence AS regclass), :value, true)"),
                                       {"sequence": sequence, "value": maximum})

        print("Migrasi selesai. PostgreSQL tidak di-truncate; SQLite tetap utuh.")
        for table, count in copied.items():
            print(f"{table}: {count} baris baru" if preserve_existing else f"{table}: {count} baris disalin")
        if preserve_existing:
            with SessionLocal() as db:
                audit_reference = source_audit_hash or f"Sumber={source.name};"
                already_logged = db.scalar(select(AuditLog.id).where(
                    AuditLog.action == "SQLiteDataImported", AuditLog.detail.contains(audit_reference)
                ))
                if not already_logged:
                    audit.append(
                        db, "system-migration", "system", "SQLiteDataImported", None, "ok",
                        f"Sumber={source.name}; audit_head={source_audit_hash or 'kosong'}; "
                        f"tabel={len(copied)}; audit_sumber={source_audit_count}; "
                        "mode=hanya-tambah; konflik_dilewati=true",
                    )
                    db.commit()
            print("Audit PostgreSQL tetap utuh; sumber audit SQLite tetap tersedia dan telah diverifikasi.")
    finally:
        target.dispose()
        sqlite_db.rollback()
        sqlite_db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("medichain_dev.db"),
                        help="path database SQLite lama (default: medichain_dev.db)")
    parser.add_argument("--merge", action="store_true",
                        help="izinkan PostgreSQL non-kosong; primary-key yang cocok ditimpa oleh SQLite")
    parser.add_argument("--preserve-existing", action="store_true",
                        help="salin hanya baris yang belum ada; jangan timpa data PostgreSQL dan pertahankan audit chain yang ada")
    args = parser.parse_args()
    if args.merge and args.preserve_existing:
        parser.error("Pilih salah satu: --merge atau --preserve-existing")
    migrate(args.source, args.merge, args.preserve_existing)


if __name__ == "__main__":
    main()
