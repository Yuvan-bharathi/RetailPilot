"""Opaque keyset cursor for cursor-paged lists (D-37, spec §11).

The movements cursor is the sort key of the last row on the page, `(occurred_at, movement_id)`, encoded as
URL-safe base64 of a small JSON object without padding. Clients must treat it as opaque; the server decodes it and
asks for rows strictly after that key in the fixed order `occurred_at DESC, movement_id DESC`.
"""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.errors import ErrorDetail, ValidationError

_MALFORMED = ErrorDetail(field="cursor", message="malformed cursor")


@dataclass(frozen=True, slots=True)
class MovementCursor:
    occurred_at: datetime
    movement_id: UUID


def encode_movement_cursor(cursor: MovementCursor) -> str:
    if cursor.occurred_at.tzinfo is None:
        raise ValueError("occurred_at must be timezone-aware")
    payload = json.dumps(
        {"t": cursor.occurred_at.isoformat(), "id": str(cursor.movement_id)}, separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_movement_cursor(token: str) -> MovementCursor:
    """Decode a cursor from `encode_movement_cursor`; anything else raises 422 VALIDATION."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        data = json.loads(raw)
        occurred_at = datetime.fromisoformat(data["t"])
        movement_id = UUID(data["id"])
    except (binascii.Error, ValueError, TypeError, KeyError) as exc:  # JSONDecodeError is a ValueError
        raise ValidationError("Invalid cursor", details=[_MALFORMED]) from exc
    if occurred_at.tzinfo is None:
        raise ValidationError("Invalid cursor", details=[_MALFORMED])
    return MovementCursor(occurred_at=occurred_at, movement_id=movement_id)
