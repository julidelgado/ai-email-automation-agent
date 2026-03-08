from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.email import Email
from app.services.ingest.imap_client import ImapClient
from app.services.ingest.parser import parse_fetched_message
from app.services.ingest.types import IngestionResult, ParsedMessage, PersistenceResult


class EmailIngestionService:
    def __init__(self, db: Session, imap_client: ImapClient | None = None):
        self.db = db
        self.imap_client = imap_client or ImapClient()

    def ingest_from_imap(self, mailbox: str, unseen_only: bool, limit: int) -> IngestionResult:
        fetched_messages = self.imap_client.fetch_messages(
            mailbox=mailbox,
            unseen_only=unseen_only,
            limit=limit,
        )

        parsed_messages = [parse_fetched_message(message) for message in fetched_messages]
        persisted = self.persist_messages(parsed_messages)

        return IngestionResult(
            fetched=len(fetched_messages),
            inserted=persisted.inserted,
            duplicates=persisted.duplicates,
            failed=persisted.failed,
        )

    def persist_messages(self, parsed_messages: list[ParsedMessage]) -> PersistenceResult:
        inserted = 0
        duplicates = 0
        failed = 0

        for message in parsed_messages:
            if self._email_exists(message.external_id):
                duplicates += 1
                continue

            email_record = Email(
                external_id=message.external_id,
                thread_id=message.thread_id,
                sender=message.sender,
                subject=message.subject,
                body_text=message.body_text,
                body_html=message.body_html,
                received_at=message.received_at,
                status="new",
            )
            try:
                self.db.add(email_record)
                self.db.commit()
                inserted += 1
            except IntegrityError:
                self.db.rollback()
                duplicates += 1
            except Exception:
                self.db.rollback()
                failed += 1

        return PersistenceResult(inserted=inserted, duplicates=duplicates, failed=failed)

    def _email_exists(self, external_id: str) -> bool:
        stmt = select(Email.id).where(Email.external_id == external_id).limit(1)
        return self.db.execute(stmt).scalar_one_or_none() is not None

