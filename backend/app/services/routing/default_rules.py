from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.rule import Rule

DEFAULT_RULES = [
    {
        "intent": "invoice",
        "action_type": "forward_to_accounting",
        "min_confidence": 0.75,
        "requires_approval": True,
        "description": "Forward invoice-related messages to accounting.",
    },
    {
        "intent": "meeting",
        "action_type": "schedule_calendar",
        "min_confidence": 0.70,
        "requires_approval": True,
        "description": "Create calendar scheduling actions for meeting-related messages.",
    },
    {
        "intent": "request",
        "action_type": "create_task",
        "min_confidence": 0.65,
        "requires_approval": True,
        "description": "Create task actions for request messages.",
    },
    {
        "intent": "other",
        "action_type": "no_action",
        "min_confidence": 1.0,
        "requires_approval": False,
        "description": "No action for unclassified/other messages.",
    },
]


def ensure_default_rules(db: Session) -> None:
    existing_intents = set(db.scalars(select(Rule.intent)))
    added = False

    for rule in DEFAULT_RULES:
        if rule["intent"] in existing_intents:
            continue
        db.add(
            Rule(
                intent=rule["intent"],
                action_type=rule["action_type"],
                min_confidence=rule["min_confidence"],
                requires_approval=rule["requires_approval"],
                is_active=True,
                description=rule["description"],
            )
        )
        added = True

    if added:
        db.commit()

