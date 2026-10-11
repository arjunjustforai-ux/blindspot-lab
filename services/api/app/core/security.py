"""Password hashing, access tokens and signed (expiring) media URLs."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import get_settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: uuid.UUID, *, extra: dict | None = None) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.jwt_expire_minutes)).timestamp()),
        "iss": "blindspot-lab",
        **(extra or {}),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=[ALGORITHM], issuer="blindspot-lab")


def decode_supabase_token(token: str) -> dict | None:
    """Verify a Supabase access token when SUPABASE_JWT_SECRET is configured."""
    s = get_settings()
    if not s.supabase_jwt_secret:
        return None
    try:
        return jwt.decode(token, s.supabase_jwt_secret, algorithms=[ALGORITHM], audience="authenticated")
    except jwt.PyJWTError:
        return None


def _media_key() -> bytes:
    return hashlib.sha256(("media:" + get_settings().jwt_secret).encode()).digest()


def sign_media(path: str, user_id: uuid.UUID, ttl: int | None = None) -> str:
    """Return a query string `exp=..&uid=..&sig=..` authorising GET of `path`."""
    exp = int(time.time()) + (ttl or get_settings().media_url_ttl_seconds)
    msg = f"{path}|{user_id}|{exp}".encode()
    sig = hmac.new(_media_key(), msg, hashlib.sha256).hexdigest()[:40]
    return f"exp={exp}&uid={user_id}&sig={sig}"


def verify_media(path: str, uid: str, exp: int, sig: str) -> bool:
    if exp < int(time.time()):
        return False
    msg = f"{path}|{uid}|{exp}".encode()
    expected = hmac.new(_media_key(), msg, hashlib.sha256).hexdigest()[:40]
    return hmac.compare_digest(expected, sig)
