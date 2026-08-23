"""Keyset pagination on (created_at DESC, id DESC).

Never OFFSET: an offset-paginated list re-scans and re-skips every prior
row on each page, which gets worse as the table grows and produces
duplicate/skipped rows if new runs are inserted between page fetches. A
keyset cursor encodes the last-seen (created_at, id) pair and the next
page is simply "rows strictly after that point in the same order" — O(page
size) regardless of how deep the list goes.
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.api.errors import AppError


@dataclass(frozen=True)
class Cursor:
    created_at: datetime
    id: uuid.UUID

    def encode(self) -> str:
        raw = f"{self.created_at.isoformat()}|{self.id}"
        return base64.urlsafe_b64encode(raw.encode()).decode()

    @staticmethod
    def decode(token: str) -> Cursor:
        try:
            raw = base64.urlsafe_b64decode(token.encode()).decode()
            created_at_raw, id_raw = raw.split("|")
            return Cursor(created_at=datetime.fromisoformat(created_at_raw), id=uuid.UUID(id_raw))
        except (ValueError, UnicodeDecodeError) as exc:
            raise AppError("invalid_cursor", "the pagination cursor is malformed") from exc
