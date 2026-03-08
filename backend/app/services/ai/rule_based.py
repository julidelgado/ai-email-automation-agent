from __future__ import annotations

from dataclasses import dataclass
import re

from app.models.email import Email
from app.services.ai.types import ClassificationOutput, ExtractedEntity

INVOICE_KEYWORDS = ("invoice", "bill", "payment due", "remittance", "po ")
MEETING_KEYWORDS = ("meeting", "calendar", "schedule", "call", "zoom", "teams")
REQUEST_KEYWORDS = ("request", "please", "can you", "need you", "todo", "action required")

INVOICE_NUMBER_PATTERNS = [
    re.compile(r"invoice(?:\s*(?:#|number|num))?\s*[:#-]?\s*([a-z0-9-]{3,})", re.IGNORECASE),
    re.compile(r"\binv[-\s]?([a-z0-9-]{3,})", re.IGNORECASE),
]
AMOUNT_PATTERN = re.compile(
    r"(?:(USD|EUR|GBP|\$|€|£)\s?(\d+(?:[.,]\d{2})?))|((\d+(?:[.,]\d{2})?)\s?(USD|EUR|GBP))",
    re.IGNORECASE,
)
DATE_PATTERN = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\w*\s+\d{1,2}(?:,\s*\d{4})?)\b",
    re.IGNORECASE,
)
TIME_PATTERN = re.compile(r"\b(\d{1,2}:\d{2}\s?(?:am|pm)?|\d{1,2}\s?(?:am|pm))\b", re.IGNORECASE)


@dataclass(slots=True)
class RuleDecision:
    intent: str
    confidence: float
    rationale: str


class RuleBasedAIProvider:
    def analyze_email(self, email: Email) -> ClassificationOutput:
        text = _normalize_text(email.subject, email.body_text, email.body_html)
        decision = _classify_text(text)
        entities = _extract_entities(intent=decision.intent, text=text, email=email)

        return ClassificationOutput(
            intent=decision.intent,
            confidence=decision.confidence,
            rationale=decision.rationale,
            entities=entities,
            model_name="rule_based",
            model_version="1.0",
        )


def _classify_text(text: str) -> RuleDecision:
    if _contains_any(text, INVOICE_KEYWORDS):
        return RuleDecision(
            intent="invoice",
            confidence=0.88,
            rationale="Invoice and billing indicators were detected in the subject/body.",
        )
    if _contains_any(text, MEETING_KEYWORDS):
        return RuleDecision(
            intent="meeting",
            confidence=0.84,
            rationale="Scheduling and meeting terms were detected in the subject/body.",
        )
    if _contains_any(text, REQUEST_KEYWORDS):
        return RuleDecision(
            intent="request",
            confidence=0.78,
            rationale="General request language was detected in the subject/body.",
        )
    return RuleDecision(
        intent="other",
        confidence=0.55,
        rationale="No strong pattern matched invoice/meeting/request categories.",
    )


def _extract_entities(intent: str, text: str, email: Email) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []
    entities.append(
        ExtractedEntity(
            entity_type=intent,
            entity_key="sender_email",
            value_text=email.sender,
            confidence=0.99,
        )
    )

    subject = (email.subject or "").strip()
    if subject:
        entities.append(
            ExtractedEntity(
                entity_type=intent,
                entity_key="subject",
                value_text=subject,
                confidence=0.98,
            )
        )

    if intent == "invoice":
        invoice_number = _find_invoice_number(text)
        if invoice_number:
            entities.append(
                ExtractedEntity(
                    entity_type="invoice",
                    entity_key="invoice_number",
                    value_text=invoice_number,
                    confidence=0.8,
                )
            )
        amount = _find_amount(text)
        if amount:
            entities.append(
                ExtractedEntity(
                    entity_type="invoice",
                    entity_key="amount",
                    value_text=amount,
                    confidence=0.72,
                )
            )

    if intent == "meeting":
        date_value = _find_first_group(DATE_PATTERN, text)
        time_value = _find_first_group(TIME_PATTERN, text)
        if date_value:
            entities.append(
                ExtractedEntity(
                    entity_type="meeting",
                    entity_key="meeting_date",
                    value_text=date_value,
                    confidence=0.7,
                )
            )
        if time_value:
            entities.append(
                ExtractedEntity(
                    entity_type="meeting",
                    entity_key="meeting_time",
                    value_text=time_value,
                    confidence=0.7,
                )
            )

    if intent == "request":
        summary = _build_request_summary(subject=subject, text=text)
        if summary:
            entities.append(
                ExtractedEntity(
                    entity_type="request",
                    entity_key="task_summary",
                    value_text=summary,
                    confidence=0.66,
                )
            )
        deadline = _find_deadline(text)
        if deadline:
            entities.append(
                ExtractedEntity(
                    entity_type="request",
                    entity_key="deadline",
                    value_text=deadline,
                    confidence=0.62,
                )
            )

    return entities


def _normalize_text(*chunks: str | None) -> str:
    combined = "\n".join([chunk for chunk in chunks if chunk]).lower()
    return re.sub(r"\s+", " ", combined).strip()


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _find_invoice_number(text: str) -> str | None:
    for pattern in INVOICE_NUMBER_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def _find_amount(text: str) -> str | None:
    match = AMOUNT_PATTERN.search(text)
    if not match:
        return None
    if match.group(1) and match.group(2):
        return f"{match.group(1)} {match.group(2)}".strip()
    if match.group(4) and match.group(5):
        return f"{match.group(4)} {match.group(5)}".strip()
    return None


def _find_first_group(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1)


def _build_request_summary(subject: str, text: str) -> str | None:
    if subject:
        return subject
    preview = text.strip()
    if not preview:
        return None
    return preview[:120]


def _find_deadline(text: str) -> str | None:
    by_match = re.search(r"\bby\s+([a-z0-9,/\-\s:apm]{3,40})", text, flags=re.IGNORECASE)
    if by_match:
        return by_match.group(1).strip()
    return _find_first_group(DATE_PATTERN, text)
