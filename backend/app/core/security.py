"""Password hashing (bcrypt) and JWT issuing/decoding (spec §5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.errors import Unauthorized


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:  # malformed hash
        return False


def create_access_token(
    user_id: UUID,
    role: str,
    store_id: UUID | None = None,
    expires_delta: timedelta | None = None,
) -> tuple[str, int]:
    """Issues a signed JWT containing sub (user_id), role, store_id. Returns (token, expires_in_seconds)."""
    settings = get_settings()
    now = datetime.now(UTC)
    delta = expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    expire = now + delta
    expires_in = int(delta.total_seconds())

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "store_id": str(store_id) if store_id else None,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    """Decodes and validates a JWT token. Raises Unauthorized on invalid or expired token."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except jwt.ExpiredSignatureError as e:
        raise Unauthorized("Token has expired") from e
    except jwt.InvalidTokenError as e:
        raise Unauthorized("Invalid authentication token") from e
