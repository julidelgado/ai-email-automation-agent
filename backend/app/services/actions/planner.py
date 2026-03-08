from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action import Action
from app.models.classification import Classification
from app.models.email import Email
from app.models.entity import Entity
from app.models.rule import Rule
from app.services.actions.audit import ActionAuditService
from app.services.actions.types import ActionPlanningBatchResult
from app.services.routing.default_rules import ensure_default_rules

logger = logging.getLogger(__name__)


class ActionPlanningService:
    def __init__(self, db: Session):
        self.db = db

    def plan_for_classified_emails(self, limit: int, statuses: list[str] | None = None) -> ActionPlanningBatchResult:
        ensure_default_rules(self.db)
        target_statuses = [status.strip() for status in (statuses or ["classified"]) if status.strip()]
        if not target_statuses:
            target_statuses = ["classified"]

        statement = (
            select(Email)
            .where(Email.status.in_(target_statuses))
            .order_by(Email.received_at.is_(None), Email.received_at, Email.id)
            .limit(limit)
        )
        emails = list(self.db.scalars(statement))

        planned = 0
        skipped = 0
        failed = 0

        for email in emails:
            try:
                was_planned = self.plan_for_email(email.id)
                if was_planned:
                    planned += 1
                else:
                    skipped += 1
            except Exception:
                logger.exception("Action planning failed for email_id=%s", email.id)
                self.db.rollback()
                failed += 1

        return ActionPlanningBatchResult(matched=len(emails), planned=planned, skipped=skipped, failed=failed)

    def plan_for_email(self, email_id: int) -> bool:
        ensure_default_rules(self.db)

        email = self.db.get(Email, email_id)
        if not email:
            raise ValueError(f"Email {email_id} does not exist.")

        if self._has_existing_action(email_id):
            return False

        classification = self._latest_classification(email_id)
        if not classification:
            return False

        rule = self._get_rule_for_intent(classification.intent)
        if not rule:
            rule = self._get_rule_for_intent("other")
        if not rule:
            raise RuntimeError("No active routing rule available.")

        action_type = rule.action_type
        status = "pending_approval" if rule.requires_approval else "pending"
        payload = self._build_payload(email, classification)

        if classification.confidence < rule.min_confidence:
            action_type = "manual_review"
            status = "pending_approval"
            payload["routing_reason"] = (
                f"Classification confidence {classification.confidence:.2f} below threshold {rule.min_confidence:.2f}."
            )

        if action_type == "no_action":
            status = "skipped"
            payload["routing_reason"] = "No action rule matched."

        action = Action(
            email_id=email.id,
            intent=classification.intent,
            action_type=action_type,
            status=status,
            idempotency_key=self._build_idempotency_key(
                email_external_id=email.external_id,
                intent=classification.intent,
                action_type=action_type,
            ),
            payload=payload,
            attempts=0,
            executed_at=datetime.now(timezone.utc) if status == "skipped" else None,
        )
        self.db.add(action)
        self.db.flush()

        ActionAuditService.record_event(
            self.db,
            action_id=action.id,
            event_type="planned",
            status=status,
            message=f"Action planned for intent={classification.intent} with action_type={action_type}.",
            details={
                "email_id": email.id,
                "intent": classification.intent,
                "rule_action_type": rule.action_type,
                "effective_action_type": action_type,
                "classification_confidence": classification.confidence,
                "rule_min_confidence": rule.min_confidence,
                "requires_approval": rule.requires_approval,
            },
        )

        if status == "pending_approval":
            email.status = "action_pending_approval"
        elif status == "pending":
            email.status = "action_pending"
        elif status == "skipped":
            email.status = "action_skipped"

        self.db.add(email)
        self.db.commit()
        return True

    def _latest_classification(self, email_id: int) -> Classification | None:
        statement = (
            select(Classification)
            .where(Classification.email_id == email_id)
            .order_by(Classification.created_at.desc(), Classification.id.desc())
            .limit(1)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def _get_rule_for_intent(self, intent: str) -> Rule | None:
        statement = select(Rule).where(Rule.intent == intent, Rule.is_active.is_(True)).limit(1)
        return self.db.execute(statement).scalar_one_or_none()

    def _has_existing_action(self, email_id: int) -> bool:
        statement = select(Action.id).where(Action.email_id == email_id).limit(1)
        return self.db.execute(statement).scalar_one_or_none() is not None

    @staticmethod
    def _build_idempotency_key(*, email_external_id: str, intent: str, action_type: str) -> str:
        raw = f"{email_external_id}|{intent}|{action_type}".encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        return f"plan-{digest[:48]}"

    def _build_payload(self, email: Email, classification: Classification) -> dict:
        entities_stmt = select(Entity).where(Entity.email_id == email.id)
        entity_rows = list(self.db.scalars(entities_stmt))

        entities: dict[str, dict] = {}
        for entity in entity_rows:
            entities[entity.entity_key] = {
                "type": entity.entity_type,
                "value_text": entity.value_text,
                "value_json": entity.value_json,
                "confidence": entity.confidence,
            }

        return {
            "classification": {
                "intent": classification.intent,
                "confidence": classification.confidence,
                "model_name": classification.model_name,
                "model_version": classification.model_version,
                "rationale": classification.rationale,
            },
            "email": {
                "id": email.id,
                "external_id": email.external_id,
                "sender": email.sender,
                "subject": email.subject,
                "received_at": email.received_at.isoformat() if email.received_at else None,
            },
            "entities": entities,
        }
