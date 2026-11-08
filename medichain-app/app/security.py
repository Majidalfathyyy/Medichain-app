"""Password hashing (scrypt), JWT, dan rate limiter."""
import hashlib
import hmac
import os
import time
import uuid
from collections import defaultdict, deque

import jwt

from .config import settings

ROLES = ("admin", "dokter", "pasien", "auditor")
ACL_ROLES = ("dokter", "pasien", "auditor")  # peran yang izinnya diatur per rekam
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc.hex(), dk)
    except Exception:
        return False


DUMMY_HASH = hash_password("dummy-untuk-menyamakan-waktu")


def create_token(user_id: int) -> str:
    """Token hanya membawa id pengguna. Peran selalu dibaca ulang dari DB,
    sehingga pencabutan peran berlaku seketika."""
    now = int(time.time())
    claims = {"sub": str(user_id), "iat": now, "exp": now + settings.jwt_minutes * 60, "jti": uuid.uuid4().hex, "iss": "medichain"}
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer="medichain",
                      options={"require": ["exp", "iat", "sub"]})


class RateLimiter:
    """Sliding window dalam memori. Untuk multi-instance gunakan Redis."""

    def __init__(self, limit: int, window: int) -> None:
        self.limit, self.window = limit, window
        self.hits: dict = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True
