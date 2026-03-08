from datetime import datetime, timezone

from sqlalchemy import func, select

from app.models.email import Email
from app.services.ingest.parser import parse_fetched_message
from app.services.ingest.service import EmailIngestionService
from app.services.ingest.types import FetchedMessage, ParsedMessage


def test_imap_pull_endpoint_requires_configuration(client):
    response = client.post("/api/v1/ingest/imap/pull", json={})

    assert response.status_code == 400
    assert "IMAP is not configured" in response.json()["detail"]


def test_parse_fetched_message_fallback_external_id_from_uid():
    raw_message = (
        b"From: Alice <alice@example.com>\r\n"
        b"Subject: Quarterly report\r\n"
        b"Date: Mon, 09 Mar 2026 10:00:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Hello team."
    )
    fetched = FetchedMessage(uid="42", raw_message=raw_message)

    parsed = parse_fetched_message(fetched)

    assert parsed.external_id == "imap:42"
    assert parsed.sender == "alice@example.com"
    assert parsed.subject == "Quarterly report"
    assert parsed.body_text == "Hello team."
    assert parsed.body_html is None
    assert parsed.received_at == datetime(2026, 3, 9, 10, 0, tzinfo=timezone.utc)


def test_persist_messages_deduplicates_by_external_id(db_session):
    service = EmailIngestionService(db_session)
    messages = [
        ParsedMessage(
            external_id="<msg-1@example.com>",
            thread_id=None,
            sender="sender@example.com",
            subject="Invoice 1001",
            body_text="Attached invoice",
            body_html=None,
            received_at=datetime(2026, 3, 8, 9, 0, tzinfo=timezone.utc),
        ),
        ParsedMessage(
            external_id="<msg-1@example.com>",
            thread_id=None,
            sender="sender@example.com",
            subject="Duplicate",
            body_text="Duplicate content",
            body_html=None,
            received_at=datetime(2026, 3, 8, 9, 5, tzinfo=timezone.utc),
        ),
        ParsedMessage(
            external_id="<msg-2@example.com>",
            thread_id=None,
            sender="another@example.com",
            subject="Meeting request",
            body_text="Can we meet tomorrow?",
            body_html=None,
            received_at=datetime(2026, 3, 8, 9, 10, tzinfo=timezone.utc),
        ),
    ]

    result = service.persist_messages(messages)
    total = db_session.execute(select(func.count()).select_from(Email)).scalar_one()

    assert result.inserted == 2
    assert result.duplicates == 1
    assert result.failed == 0
    assert total == 2

