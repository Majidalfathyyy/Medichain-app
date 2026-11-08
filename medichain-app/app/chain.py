"""Klien blockchain. Dua implementasi dengan antarmuka sama:
MockChain : ledger lokal (dev/tes) tanpa node.
Web3Chain : smart contract MediChain.sol di Ethereum testnet / Hardhat.
Semua hash dan key berupa hex 64 karakter (bytes32)."""
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Protocol

from .config import settings


@dataclass(frozen=True)
class Tx:
    tx_hash: str
    block: int


@dataclass(frozen=True)
class OnChain:
    hash_record: str
    hash_ecg: str
    version: int
    timestamp: int


class ChainClient(Protocol):
    def register(self, key: str, hr: str, he: str, version: int = 1) -> Tx: ...
    def update(self, key: str, hr: str, he: str) -> Tx: ...
    def get(self, key: str) -> Optional[OnChain]: ...
    def has_access(self, key: str, role_hash: str) -> bool: ...
    def grant(self, key: str, role_hash: str) -> Tx: ...
    def revoke(self, key: str, role_hash: str) -> Tx: ...
    def log_access(self, key: str, action: str) -> Tx: ...


class MockChain:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path, self.lock = path, threading.Lock()
        self.recs: dict = {}
        self.txs: list = []
        self.accesses: dict = {}
        if path and os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
            self.recs, self.txs = d["recs"], d["txs"]
            self.accesses = d.get("accesses", {})

    def _tx(self, kind: str, key: str, data: dict) -> Tx:
        prev = self.txs[-1]["tx"] if self.txs else "0" * 64
        n = len(self.txs)
        tx = hashlib.sha256(f"{prev}{kind}{key}{json.dumps(data, sort_keys=True)}{time.time_ns()}{n}".encode()).hexdigest()
        self.txs.append({"tx": tx, "kind": kind, "key": key, "block": 1_000_000 + n})
        if self.path:
            with open(self.path, "w") as f:
                json.dump({"recs": self.recs, "txs": self.txs, "accesses": self.accesses}, f)
        return Tx("0x" + tx, 1_000_000 + n)

    def register(self, key: str, hr: str, he: str, version: int = 1) -> Tx:
        with self.lock:
            if key in self.recs:
                raise RuntimeError("Rekam sudah terdaftar")
            self.recs[key] = {"hr": hr, "he": he, "v": version, "ts": int(time.time())}
            return self._tx("RecordRegistered", key, {"hr": hr, "he": he, "version": version})

    def update(self, key: str, hr: str, he: str) -> Tx:
        with self.lock:
            if key not in self.recs:
                raise RuntimeError("Rekam belum terdaftar")
            r = self.recs[key]
            r.update(hr=hr, he=he, v=r["v"] + 1, ts=int(time.time()))
            return self._tx("RecordUpdated", key, {"hr": hr, "he": he})

    def get(self, key: str) -> Optional[OnChain]:
        r = self.recs.get(key)
        return OnChain(r["hr"], r["he"], r["v"], r["ts"]) if r else None

    def grant(self, key: str, role_hash: str) -> Tx:
        with self.lock:
            tx = self._tx("AccessGranted", key, {"role": role_hash})
            self.accesses[f"{key}:{role_hash}"] = True
            if self.path:
                with open(self.path, "w") as f:
                    json.dump({"recs": self.recs, "txs": self.txs, "accesses": self.accesses}, f)
            return tx

    def revoke(self, key: str, role_hash: str) -> Tx:
        with self.lock:
            tx = self._tx("AccessRevoked", key, {"role": role_hash})
            self.accesses[f"{key}:{role_hash}"] = False
            if self.path:
                with open(self.path, "w") as f:
                    json.dump({"recs": self.recs, "txs": self.txs, "accesses": self.accesses}, f)
            return tx

    def has_access(self, key: str, role_hash: str) -> bool:
        return bool(self.accesses.get(f"{key}:{role_hash}", False))

    def log_access(self, key: str, action: str) -> Tx:
        with self.lock:
            return self._tx("AccessLogged", key, {"action": action})


def _fn(name, ins, outs=(), mut="nonpayable"):
    return {"type": "function", "name": name, "stateMutability": mut,
            "inputs": [{"name": f"a{i}", "type": t} for i, t in enumerate(ins)],
            "outputs": [{"name": f"o{i}", "type": t} for i, t in enumerate(outs)]}


ABI = [
    _fn("registerRecord", ["bytes32"] * 3), _fn("updateRecord", ["bytes32"] * 3),
    _fn("registerRecordAtVersion", ["bytes32"] * 3 + ["uint32"]),
    _fn("getRecord", ["bytes32"], ["bytes32", "bytes32", "uint32", "uint64"], "view"),
    _fn("writers", ["address"], ["bool"], "view"),
    _fn("access", ["bytes32", "bytes32"], ["bool"], "view"),
    _fn("grantAccess", ["bytes32"] * 2), _fn("revokeAccess", ["bytes32"] * 2),
    _fn("logAccess", ["bytes32", "string"]),
]


class Web3Chain:
    def __init__(self) -> None:
        from web3 import Web3  # impor lambat agar mode mock tidak butuh web3
        self.w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 30}))
        self.acct = self.w3.eth.account.from_key(settings.chain_private_key)
        self.c = self.w3.eth.contract(address=Web3.to_checksum_address(settings.contract_address), abi=ABI)
        self.lock = threading.Lock()

    def _ensure_ready(self) -> None:
        if not self.w3.is_connected():
            raise RuntimeError("RPC blockchain tidak dapat dihubungi")
        actual_chain_id = self.w3.eth.chain_id
        if actual_chain_id != settings.chain_id:
            raise RuntimeError(f"RPC terhubung ke chain ID {actual_chain_id}, bukan {settings.chain_id}")
        if not self.w3.eth.get_code(self.c.address):
            raise RuntimeError("Tidak ada smart contract di CONTRACT_ADDRESS")
        if not self.c.functions.writers(self.acct.address).call():
            raise RuntimeError("Akun backend belum terdaftar sebagai writer di smart contract")

    def _send(self, fn) -> Tx:
        with self.lock:  # serialkan nonce
            self._ensure_ready()
            tx = fn.build_transaction({"from": self.acct.address, "chainId": self.w3.eth.chain_id,
                                       "nonce": self.w3.eth.get_transaction_count(self.acct.address, "pending")})
            signed = self.acct.sign_transaction(tx)
            raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
            h = self.w3.eth.send_raw_transaction(raw)
            r = self.w3.eth.wait_for_transaction_receipt(h, timeout=120)
            if r.status != 1:
                raise RuntimeError("Transaksi ditolak smart contract")
            return Tx("0x" + h.hex().removeprefix("0x"), r.blockNumber)

    @staticmethod
    def _b(x: str) -> bytes:
        return bytes.fromhex(x)

    def register(self, key, hr, he, version=1):
        if version == 1:
            fn = self.c.functions.registerRecord(self._b(key), self._b(hr), self._b(he))
        else:
            fn = self.c.functions.registerRecordAtVersion(self._b(key), self._b(hr), self._b(he), version)
        return self._send(fn)
    def update(self, key, hr, he): return self._send(self.c.functions.updateRecord(self._b(key), self._b(hr), self._b(he)))
    def grant(self, key, rh): return self._send(self.c.functions.grantAccess(self._b(key), self._b(rh)))
    def revoke(self, key, rh): return self._send(self.c.functions.revokeAccess(self._b(key), self._b(rh)))
    def log_access(self, key, action): return self._send(self.c.functions.logAccess(self._b(key), action[:64]))

    def get(self, key: str) -> Optional[OnChain]:
        self._ensure_ready()
        hr, he, v, ts = self.c.functions.getRecord(self._b(key)).call()
        return OnChain(hr.hex().removeprefix("0x"), he.hex().removeprefix("0x"), v, ts) if v else None

    def has_access(self, key: str, role_hash: str) -> bool:
        self._ensure_ready()
        return bool(self.c.functions.access(self._b(key), self._b(role_hash)).call())


def chain_metadata() -> dict:
    if settings.chain_mode == "web3":
        return {"mode": "web3", "network": settings.chain_name, "chain_id": settings.chain_id,
                "explorer_tx_base": settings.explorer_tx_base}
    return {"mode": "mock", "network": "MockChain", "chain_id": None, "explorer_tx_base": None}


@lru_cache(maxsize=1)
def get_chain():
    return Web3Chain() if settings.chain_mode == "web3" else MockChain(settings.mock_chain_file)
