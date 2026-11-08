"""Import trusted record snapshots from an existing MockChain ledger.

Useful when a local API and Docker use different MockChain files. The source
ledger, not current SQL contents, is authoritative for hashes and versions.
Existing destination conflicts stop the whole import before anything is queued.
"""
import argparse
import json
from pathlib import Path

from sqlalchemy import func, select

from app import audit, services
from app.chain import MockChain, get_chain
from app.chain_ops import enqueue_record_register, process_pending
from app.config import settings
from app.db import ChainOperation, Record, SessionLocal
from app.hashing import chain_key, same


def _valid_hash(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        bytes.fromhex(value)
        return True
    except ValueError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import current record anchors from a trusted MockChain JSON ledger."
    )
    parser.add_argument("--source", required=True, help="path to the trusted source MockChain JSON file")
    parser.add_argument("--dry-run", action="store_true", help="check compatibility without writing")
    args = parser.parse_args()

    if settings.chain_mode != "mock":
        raise SystemExit("Set CHAIN_MODE=mock before importing a MockChain ledger.")
    target = get_chain()
    if not isinstance(target, MockChain):
        raise SystemExit("Configured destination chain is not MockChain; no changes made.")

    try:
        source_data = json.loads(Path(args.source).read_text(encoding="utf-8"))
        source_records = source_data["recs"]
        source_tx_count = len(source_data.get("txs", []))
        if not isinstance(source_records, dict):
            raise ValueError("ledger sections have invalid types")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Cannot read a valid source MockChain ledger: {exc}") from None

    with SessionLocal() as db:
        broken = audit.verify_chain(db)
        if broken is not None:
            raise SystemExit(f"Audit trail is damaged at row {broken}; import cancelled.")
        pending = db.scalar(select(ChainOperation.id).where(ChainOperation.status == "pending").limit(1))
        if pending is not None:
            raise SystemExit("Pending chain operations exist; synchronize them before importing.")

        records = list(db.scalars(select(Record).order_by(Record.id)))
        plans: list[tuple[Record, str, str, str, int]] = []
        modified = 0

        # Read-only preflight: never anchor a current SQL hash in place of a
        # trusted historical source hash. This preserves tampering detection.
        for rec in records:
            key = chain_key(rec.id)
            source_rec = source_records.get(key)
            if not isinstance(source_rec, dict):
                raise SystemExit(
                    "The source ledger is missing a database record; import cancelled without changes."
                )
            hr, he, version = source_rec.get("hr"), source_rec.get("he"), source_rec.get("v")
            if not _valid_hash(hr) or not _valid_hash(he) or not isinstance(version, int) or version < 1:
                raise SystemExit("The source ledger contains an invalid record snapshot; import cancelled.")

            local_hr, local_he = services.local_hashes(db, rec)
            if rec.version != version or not same(local_hr, hr) or not same(local_he, he):
                modified += 1

            current = target.get(key)
            if current and (
                current.version != version
                or not same(current.hash_record, hr)
                or not same(current.hash_ecg, he)
            ):
                raise SystemExit(
                    "The destination MockChain conflicts with the trusted source ledger; "
                    "nothing was queued. Review the two ledgers before proceeding."
                )
            plans.append((rec, key, hr, he, version))

        missing = sum(1 for _, key, *_ in plans if target.get(key) is None)
        print(f"Destination MockChain file: {settings.mock_chain_file}")
        print(f"Trusted source ledger transactions: {source_tx_count}")
        print(f"Database records checked: {len(records)}; snapshots to import: {missing}")
        print(f"Current SQL snapshots differing from source (will remain detectable): {modified}")
        print("Access permissions are left unchanged by this record integrity import.")
        if args.dry_run:
            print("Dry run complete. No database or MockChain entries were changed.")
            return

        for rec, key, hr, he, version in plans:
            if target.get(key) is None:
                enqueue_record_register(db, rec.id, key, hr, he,
                                        "mockchain-ledger-import", "system", version)
        db.commit()

        while True:
            batch_completed = process_pending(db, target, limit=100)
            remaining = db.scalar(
                select(func.count()).select_from(ChainOperation).where(ChainOperation.status == "pending")
            ) or 0
            if not remaining:
                break
            if batch_completed == 0:
                raise SystemExit(
                    "Some imports remain pending. Inspect /chain/status and retry after resolving the error."
                )
        print(f"Import complete: {missing} trusted record snapshots registered.")
        print("Clinical database rows and access permissions were not changed; differing SQL hashes remain detectable.")


if __name__ == "__main__":
    main()
