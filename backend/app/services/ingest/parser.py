from __future__ import annotations

from datetime import timezone
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
import hashlib

from app.services.ingest.types import FetchedMessage, ParsedMessage


def parse_fetched_message(message: FetchedMessage) -> ParsedMessage:
    parsed = BytesParser(policy=policy.default).parsebytes(message.raw_message)

    message_id = _clean_header(parsed.get("Message-ID"))
    external_id = _build_external_id(message_id=message_id, uid=message.uid, raw_message=message.raw_message)
    thread_id = _extract_thread_id(parsed)
    sender = _extract_sender(parsed.get("From"))
    subject = _clean_header(parsed.get("Subject"))
    received_at = _parse_received_at(parsed.get("Date"))
    body_text, body_html = _extract_bodies(parsed)

    return ParsedMessage(
        external_id=external_id,
        thread_id=thread_id,
        sender=sender,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        received_at=received_at,
    )


def _build_external_id(message_id: str | None, uid: str, raw_message: bytes) -> str:
    if message_id:
        return message_id[:255]
    if uid:
        return f"imap:{uid}"[:255]
    digest = hashlib.sha256(raw_message).hexdigest()
    return f"sha256:{digest}"[:255]


def _extract_thread_id(parsed_message) -> str | None:
    explicit = _clean_header(parsed_message.get("Thread-Index")) or _clean_header(parsed_message.get("X-GM-THRID"))
    if explicit:
        return explicit[:255]

    in_reply_to = _clean_header(parsed_message.get("In-Reply-To"))
    if in_reply_to:
        return in_reply_to[:255]

    references = _clean_header(parsed_message.get("References"))
    if not references:
        return None

    last_reference = references.split()[-1].strip()
    return last_reference[:255] if last_reference else None


def _extract_sender(raw_from: str | None) -> str:
    _, address = parseaddr(raw_from or "")
    if address:
        return address[:320]

    cleaned = _clean_header(raw_from)
    if cleaned:
        return cleaned[:320]

    return "unknown@unknown"


def _parse_received_at(raw_date: str | None):
    if not raw_date:
        return None
    try:
        dt = parsedate_to_datetime(raw_date)
    except (TypeError, ValueError):
        return None

    if dt is None:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _extract_bodies(parsed_message) -> tuple[str | None, str | None]:
    text_parts: list[str] = []
    html_parts: list[str] = []

    if parsed_message.is_multipart():
        for part in parsed_message.walk():
            if part.is_multipart():
                continue
            if part.get_content_disposition() == "attachment":
                continue
            part_content_type = part.get_content_type()
            part_body = _safe_part_body(part)
            if not part_body:
                continue
            if part_content_type == "text/plain":
                text_parts.append(part_body)
            elif part_content_type == "text/html":
                html_parts.append(part_body)
    else:
        part_content_type = parsed_message.get_content_type()
        part_body = _safe_part_body(parsed_message)
        if part_body:
            if part_content_type == "text/html":
                html_parts.append(part_body)
            else:
                text_parts.append(part_body)

    text = "\n\n".join(text_parts).strip() if text_parts else None
    html = "\n\n".join(html_parts).strip() if html_parts else None
    return text or None, html or None


def _safe_part_body(part) -> str | None:
    try:
        value = part.get_content()
    except (LookupError, UnicodeDecodeError):
        payload = part.get_payload(decode=True)
        if payload is None:
            return None
        charset = part.get_content_charset() or "utf-8"
        value = payload.decode(charset, errors="replace")

    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return None


def _clean_header(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None

