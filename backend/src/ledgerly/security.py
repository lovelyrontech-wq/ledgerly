from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

ALGORITHM = "HS256"
MIN_SECRET_LENGTH = 32

# Used when the email is unknown, so a failed login takes the same time either way
# and the response time does not reveal which emails exist.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt(rounds=10))


class InvalidTokenError(Exception):
    pass


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        bcrypt.checkpw(password.encode("utf-8"), _DUMMY_HASH)
        return False
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: str, secret: str, ttl_minutes: int, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    payload = {"sub": user_id, "iat": issued, "exp": issued + timedelta(minutes=ttl_minutes)}
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, secret: str) -> str:
    """Return the user ID in the token. Raise InvalidTokenError if it is invalid or expired."""
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM], options={"require": ["sub", "exp", "iat"]})
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise InvalidTokenError("token has no subject")
    return user_id
