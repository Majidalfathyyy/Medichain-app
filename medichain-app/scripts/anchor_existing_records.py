"""Anchor existing current DB snapshots to a newly deployed Web3 contract."""
import argparse
from decimal import Decimal

from sqlalchemy import select

from app import audit, services
from app.chain import get_chain
from app.chain_ops import enqueue_access, enqueue_record_register, process_pending
from app.config import settings
from app.db import Access, ChainOperation, Record, SessionLocal
from app.hashing import chain_key, role_hash


SAFETY_MULTIPLIER = Decimal("1.25")
NEW_RECORD_GRANT_GAS_CAP = 100_000


def _preflight(db, chain) -> tuple[int, int, int, int, int]:
    """Estimate the anchor writes and confirm balance before queuing any SQL rows."""
    from app.chain import Web3Chain

    if not isinstance(chain, Web3Chain):
        raise SystemExit("Preflight memerlukan CHAIN_MODE=web3.")
    try:
        chain._ensure_ready()
        pending_id = db.scalar(select(ChainOperation.id).where(ChainOperation.status == "pending").limit(1))
        if pending_id is not None:
            raise RuntimeError("Ada operasi blockchain pending; selesaikan antrean sebelum preflight penjangan.")

        records = list(db.scalars(select(Record).order_by(Record.id)))
        estimates: list[int] = []
        register_count = 0
        access_count = 0
        for rec in records:
            key = chain_key(rec.id)
            hash_record, hash_ecg = services.local_hashes(db, rec)
            current = chain.get(key)
            if current:
                if (current.version != rec.version or current.hash_record != hash_record
                        or current.hash_ecg != hash_ecg):
                    raise RuntimeError(f"Rekam {rec.id} sudah ada di chain tetapi versi/hash berbeda; tidak ditimpa.")
            else:
                if rec.version == 1:
                    fn = chain.c.functions.registerRecord(chain._b(key), chain._b(hash_record), chain._b(hash_ecg))
                else:
                    fn = chain.c.functions.registerRecordAtVersion(
                        chain._b(key), chain._b(hash_record), chain._b(hash_ecg), rec.version
                    )
                estimates.append(fn.estimate_gas({"from": chain.acct.address}))
                register_count += 1

            accesses = list(db.scalars(select(Access).where(Access.record_id == rec.id)))
            for access in accesses:
                role = role_hash(access.role)
                if not current and access.allowed:
                    # grantAccess requires a registered record, so an RPC estimate
                    # would revert before the registration transaction is sent.
                    # Use a conservative gas cap for the simple storage write.
                    estimates.append(NEW_RECORD_GRANT_GAS_CAP)
                    access_count += 1
                elif chain.has_access(key, role) != bool(access.allowed):
                    fn = (chain.c.functions.grantAccess(chain._b(key), chain._b(role)) if access.allowed
                          else chain.c.functions.revokeAccess(chain._b(key), chain._b(role)))
                    estimates.append(fn.estimate_gas({"from": chain.acct.address}))
                    access_count += 1

        gas_price = chain.w3.eth.gas_price
        raw_cost = sum(estimates) * gas_price
        buffered_cost = int(Decimal(raw_cost) * SAFETY_MULTIPLIER)
        balance = chain.w3.eth.get_balance(chain.acct.address)
        fmt = lambda wei: f"{Decimal(wei) / Decimal(10**18):.8f} SepoliaETH"
        print(f"Jaringan: {settings.chain_name} (chain ID {settings.chain_id})")
        print(f"Rekam diperiksa: {len(records)}; transaksi register: {register_count}; transaksi ACL: {access_count}")
        print(f"Estimasi pada gas price saat ini: {fmt(raw_cost)}; dengan cadangan 25%: {fmt(buffered_cost)}")
        print(f"Saldo akun backend: {fmt(balance)}")
        print("Biaya deployment kontrak tidak termasuk dalam estimasi ini.")
        if balance < buffered_cost:
            raise RuntimeError(f"Saldo kurang dari estimasi plus cadangan 25%; kekurangan sekitar {fmt(buffered_cost - balance)}")
        return len(records), register_count, access_count, raw_cost, buffered_cost
    except Exception as exc:
        message = str(exc).replace(settings.rpc_url, "[RPC_URL]") if settings.rpc_url else str(exc)
        raise SystemExit(f"Preflight Sepolia gagal: {message}") from None


def main() -> None:
    parser = argparse.ArgumentParser(description="Periksa biaya penjangan Sepolia tanpa menulis transaksi.")
    parser.add_argument("--dry-run", action="store_true", help="hanya estimasi; tidak mengantre atau mengirim transaksi")
    args = parser.parse_args()
    if settings.chain_mode != "web3":
        raise SystemExit("Set CHAIN_MODE=web3 and Sepolia settings before anchoring records.")
    chain = get_chain()
    with SessionLocal() as db:
        broken = audit.verify_chain(db)
        if broken is not None:
            raise SystemExit(f"Audit trail rusak pada baris {broken}; anchoring dibatalkan.")
        _preflight(db, chain)
        if args.dry_run:
            print("Dry run selesai. Tidak ada data database atau blockchain yang diubah.")
            return
        records = list(db.scalars(select(Record).order_by(Record.id)))
        for rec in records:
            key = chain_key(rec.id)
            hash_record, hash_ecg = services.local_hashes(db, rec)
            current = chain.get(key)
            if current:
                if (current.version != rec.version or current.hash_record != hash_record
                        or current.hash_ecg != hash_ecg):
                    raise SystemExit(f"Rekam {rec.id} sudah ada di chain tetapi versi/hash berbeda; tidak ditimpa.")
            else:
                enqueue_record_register(db, rec.id, key, hash_record, hash_ecg,
                                        "sepolia-migration", "system", rec.version)
                audit.append(db, "sepolia-migration", "system", "RecordAnchoringQueued", rec.id,
                             "pending", f"snapshot saat ini versi {rec.version}")
            for access in db.scalars(select(Access).where(Access.record_id == rec.id)):
                enqueue_access(db, rec.id, key, role_hash(access.role), access.allowed,
                               "sepolia-migration", "system")
        db.commit()
        completed = process_pending(db, chain, limit=100)
        pending = db.scalar(select(ChainOperation.id).where(ChainOperation.status == "pending").limit(1))
        print(f"Snapshot diperiksa: {len(records)}; operasi berhasil: {completed}; masih pending: {bool(pending)}")
        print("Riwayat sebelum deployment Sepolia tidak dibuat ulang; yang dicatat adalah snapshot saat ini.")


if __name__ == "__main__":
    main()
