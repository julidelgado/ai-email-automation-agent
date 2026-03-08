from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.classification import Classification
from app.models.email import Email
from app.models.entity import Entity
from app.services.ai.ollama_provider import OllamaAIProvider
from app.services.ai.rule_based import RuleBasedAIProvider
from app.services.ai.types import ClassificationBatchResult, ClassificationOutput

logger = logging.getLogger(__name__)


class ClassificationPipelineService:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        rule_based_provider: RuleBasedAIProvider | None = None,
        ollama_provider: OllamaAIProvider | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.rule_based_provider = rule_based_provider or RuleBasedAIProvider()
        self.ollama_provider = ollama_provider or OllamaAIProvider(self.settings)

    def process_pending_emails(self, limit: int, statuses: list[str] | None = None) -> ClassificationBatchResult:
        normalized_statuses = [status.strip() for status in (statuses or ["new"]) if status.strip()]
        if not normalized_statuses:
            normalized_statuses = ["new"]

        pending_emails = self._load_pending_emails(limit=limit, statuses=normalized_statuses)
        processed = 0
        failed = 0

        for email in pending_emails:
            try:
                analysis = self._analyze(email)
                self._persist_analysis(email, analysis)
                processed += 1
            except Exception:
                logger.exception("Classification failed for email_id=%s", email.id)
                self.db.rollback()
                self._mark_classification_error(email)
                failed += 1

        return ClassificationBatchResult(matched=len(pending_emails), processed=processed, failed=failed)

    def _load_pending_emails(self, limit: int, statuses: list[str]) -> list[Email]:
        statement = (
            select(Email)
            .where(Email.status.in_(statuses))
            .order_by(Email.received_at.is_(None), Email.received_at, Email.id)
            .limit(limit)
        )
        return list(self.db.scalars(statement))

    def _analyze(self, email: Email) -> ClassificationOutput:
        provider_name = self.settings.ai_provider.strip().lower()
        if provider_name == "ollama":
            try:
                return self.ollama_provider.analyze_email(email)
            except Exception:
                logger.exception("Ollama analysis failed for email_id=%s, falling back to rule_based", email.id)

        return self.rule_based_provider.analyze_email(email)

    def _persist_analysis(self, email: Email, analysis: ClassificationOutput) -> None:
        self.db.execute(delete(Classification).where(Classification.email_id == email.id))
        self.db.execute(delete(Entity).where(Entity.email_id == email.id))

        classification = Classification(
            email_id=email.id,
            intent=analysis.intent,
            confidence=analysis.confidence,
            model_name=analysis.model_name,
            model_version=analysis.model_version,
            rationale=analysis.rationale,
        )
        self.db.add(classification)

        for entity in analysis.entities:
            self.db.add(
                Entity(
                    email_id=email.id,
                    entity_type=entity.entity_type,
                    entity_key=entity.entity_key,
                    value_text=entity.value_text,
                    value_json=entity.value_json,
                    confidence=entity.confidence,
                )
            )

        email.status = "classified"
        self.db.add(email)
        self.db.commit()

    def _mark_classification_error(self, email: Email) -> None:
        try:
            email.status = "classification_error"
            self.db.add(email)
            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.exception("Failed to persist classification_error status for email_id=%s", email.id)

