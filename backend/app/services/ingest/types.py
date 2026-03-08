from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class FetchedMessage:
    uid: str
    raw_message: bytes


@dataclass(slots=True)
class ParsedMessage:
    external_id: str
    thread_id: str | None
    sender: str
    subject: str | None
    body_text: str | None
    body_html: str | None
    received_at: datetime | None


@dataclass(slots=True)
class PersistenceResult:
    inserted: int
    duplicates: int
    failed: int


@dataclass(slots=True)
class IngestionResult:
    fetched: int
    inserted: int
    duplicates: int
    failed: int

