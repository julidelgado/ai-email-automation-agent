from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.models.classification import Classification
from app.models.email import Email
from app.models.entity import Entity
from app.services.ai.pipeline import ClassificationPipelineService
from app.services.ai.rule_based import RuleBasedAIProvider
from app.workers.scheduler import run_classification_job


def test_rule_based_provider_detects_invoice_entities():
    provider = RuleBasedAIProvider()
    email = Email(
        external_id="<invoice-1@example.com>",
        sender="billing@vendor.com",
        subject="Invoice #INV-2026-100",
        body_text="Please process invoice INV-2026-100 for $123.45 by 03/20/2026.",
        status="new",
    )

    result = provider.analyze_email(email)
    keys = {entity.entity_key for entity in result.entities}

    assert result.intent == "invoice"
    assert result.confidence >= 0.8
    assert "invoice_number" in keys
    assert "amount" in keys


def test_classification_pipeline_processes_pending_new_email(db_session):
    email = Email(
        external_id="<meeting-1@example.com>",
        sender="manager@example.com",
        subject="Meeting tomorrow at 10am",
        body_text="Can we schedule a meeting on Mar 10, 2026 at 10:00 am?",
        received_at=datetime(2026, 3, 9, 8, 0, tzinfo=timezone.utc),
        status="new",
    )
    db_session.add(email)
    db_session.commit()

    pipeline = ClassificationPipelineService(db_session)
    result = pipeline.process_pending_emails(limit=20, statuses=["new"])

    classification = db_session.execute(select(Classification).where(Classification.email_id == email.id)).scalar_one()
    entities = list(db_session.scalars(select(Entity).where(Entity.email_id == email.id)))
    refreshed_email = db_session.execute(select(Email).where(Email.id == email.id)).scalar_one()

    assert result.matched == 1
    assert result.processed == 1
    assert result.failed == 0
    assert classification.intent == "meeting"
    assert len(entities) >= 2
    assert refreshed_email.status == "classified"


def test_pipeline_endpoint_classifies_pending_emails(client, db_session):
    email = Email(
        external_id="<request-1@example.com>",
        sender="ceo@example.com",
        subject="Request: create Q2 planning task",
        body_text="Please create this task by March 15.",
        received_at=datetime(2026, 3, 9, 9, 0, tzinfo=timezone.utc),
        status="new",
    )
    db_session.add(email)
    db_session.commit()

    response = client.post("/api/v1/pipeline/classify", json={"limit": 10, "statuses": ["new"]})
    payload = response.json()

    classification = db_session.execute(select(Classification).where(Classification.email_id == email.id)).scalar_one()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["processed"] == 1
    assert payload["failed"] == 0
    assert classification.intent == "request"


def test_scheduled_classification_job_processes_new_email(db_session):
    email = Email(
        external_id="<invoice-2@example.com>",
        sender="vendor@example.com",
        subject="Invoice number 7755",
        body_text="Invoice #7755 amount EUR 980.00",
        received_at=datetime(2026, 3, 9, 9, 30, tzinfo=timezone.utc),
        status="new",
    )
    db_session.add(email)
    db_session.commit()

    run_classification_job()
    db_session.expire_all()

    refreshed_email = db_session.execute(select(Email).where(Email.id == email.id)).scalar_one()
    classification = db_session.execute(select(Classification).where(Classification.email_id == email.id)).scalar_one()

    assert refreshed_email.status == "classified"
    assert classification.intent == "invoice"
