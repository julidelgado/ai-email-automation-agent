from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.models.action import Action
from app.models.action_dispatch import ActionDispatch
from app.models.action_event import ActionEvent
from app.models.classification import Classification
from app.models.email import Email
from app.models.entity import Entity
from app.models.task import Task
from app.services.actions.executor import ActionExecutionService
from app.workers.scheduler import run_action_execution_job, run_action_planning_job


def _create_classified_email(
    db_session,
    *,
    external_id: str,
    sender: str,
    subject: str,
    body_text: str,
    intent: str,
    confidence: float,
    entity_key: str | None = None,
    entity_value: str | None = None,
) -> Email:
    email = Email(
        external_id=external_id,
        sender=sender,
        subject=subject,
        body_text=body_text,
        received_at=datetime(2026, 3, 9, 10, 0, tzinfo=timezone.utc),
        status="classified",
    )
    db_session.add(email)
    db_session.flush()

    db_session.add(
        Classification(
            email_id=email.id,
            intent=intent,
            confidence=confidence,
            model_name="rule_based",
            model_version="1.0",
            rationale="test fixture",
        )
    )
    if entity_key and entity_value:
        db_session.add(
            Entity(
                email_id=email.id,
                entity_type=intent,
                entity_key=entity_key,
                value_text=entity_value,
                value_json=None,
                confidence=0.9,
            )
        )
    db_session.commit()
    return email


def test_plan_actions_endpoint_creates_pending_approval_action(client, db_session):
    email = _create_classified_email(
        db_session,
        external_id="<req-01@example.com>",
        sender="lead@example.com",
        subject="Request: publish release notes",
        body_text="Please publish release notes by Friday.",
        intent="request",
        confidence=0.9,
    )

    response = client.post("/api/v1/actions/plan", json={"limit": 10, "statuses": ["classified"]})
    payload = response.json()
    db_session.expire_all()

    action = db_session.execute(select(Action).where(Action.email_id == email.id)).scalar_one()
    refreshed_email = db_session.get(Email, email.id)

    assert response.status_code == 200
    assert payload["planned"] == 1
    assert action.action_type == "create_task"
    assert action.status == "pending_approval"
    assert refreshed_email.status == "action_pending_approval"


def test_approve_action_executes_request_and_creates_task(client, db_session):
    email = _create_classified_email(
        db_session,
        external_id="<req-02@example.com>",
        sender="ops@example.com",
        subject="Request: prepare weekly report",
        body_text="Please prepare the weekly report by March 15.",
        intent="request",
        confidence=0.92,
        entity_key="task_summary",
        entity_value="prepare weekly report",
    )
    client.post("/api/v1/actions/plan", json={"limit": 10, "statuses": ["classified"]})
    action = db_session.execute(select(Action).where(Action.email_id == email.id)).scalar_one()

    response = client.post(f"/api/v1/actions/{action.id}/approve", json={"execute_now": True})
    payload = response.json()
    db_session.expire_all()

    executed_action = db_session.get(Action, action.id)
    task = db_session.execute(select(Task).where(Task.email_id == email.id)).scalar_one()
    refreshed_email = db_session.get(Email, email.id)

    assert response.status_code == 200
    assert payload["action"]["status"] == "executed"
    assert executed_action.status == "executed"
    assert task.title == "prepare weekly report"
    assert refreshed_email.status == "action_executed"


def test_reject_action_endpoint_marks_rejected(client, db_session):
    email = _create_classified_email(
        db_session,
        external_id="<meeting-02@example.com>",
        sender="manager@example.com",
        subject="Meeting tomorrow",
        body_text="Let's meet tomorrow at 10:00am.",
        intent="meeting",
        confidence=0.88,
    )
    client.post("/api/v1/actions/plan", json={"limit": 10, "statuses": ["classified"]})
    action = db_session.execute(select(Action).where(Action.email_id == email.id)).scalar_one()

    response = client.post(f"/api/v1/actions/{action.id}/reject", json={"reason": "Not needed"})
    db_session.expire_all()

    rejected_action = db_session.get(Action, action.id)
    refreshed_email = db_session.get(Email, email.id)

    assert response.status_code == 200
    assert rejected_action.status == "rejected"
    assert refreshed_email.status == "action_rejected"


def test_execute_invoice_action_fails_without_smtp_config(db_session):
    email = _create_classified_email(
        db_session,
        external_id="<inv-03@example.com>",
        sender="vendor@example.com",
        subject="Invoice #7781",
        body_text="Invoice #7781 amount $250.00",
        intent="invoice",
        confidence=0.95,
        entity_key="invoice_number",
        entity_value="7781",
    )
    action = Action(
        email_id=email.id,
        intent="invoice",
        action_type="forward_to_accounting",
        status="pending",
        payload={"entities": {"invoice_number": {"value_text": "7781"}, "amount": {"value_text": "$250.00"}}},
        attempts=0,
    )
    db_session.add(action)
    db_session.commit()

    service = ActionExecutionService(db_session)
    result = service.execute_action(action.id)
    db_session.expire_all()

    failed_action = db_session.get(Action, action.id)
    refreshed_email = db_session.get(Email, email.id)
    events = list(db_session.scalars(select(ActionEvent).where(ActionEvent.action_id == action.id)))

    assert result.status == "retry_pending"
    assert failed_action.status == "retry_pending"
    assert failed_action.next_attempt_at is not None
    assert "APP_ACTION_INVOICE_ACCOUNTING_EMAIL" in (failed_action.error_message or "")
    assert refreshed_email.status == "action_retry_pending"
    assert any(event.event_type == "retry_scheduled" for event in events)


def test_retry_pending_action_becomes_dead_letter_after_max_attempts(db_session):
    email = _create_classified_email(
        db_session,
        external_id="<inv-04@example.com>",
        sender="vendor@example.com",
        subject="Invoice #7782",
        body_text="Invoice #7782 amount $100.00",
        intent="invoice",
        confidence=0.95,
    )
    action = Action(
        email_id=email.id,
        intent="invoice",
        action_type="forward_to_accounting",
        status="pending",
        payload={"entities": {"invoice_number": {"value_text": "7782"}, "amount": {"value_text": "$100.00"}}},
        attempts=0,
    )
    db_session.add(action)
    db_session.commit()

    service = ActionExecutionService(db_session)
    service.execute_action(action.id)  # attempt 1 -> retry_pending

    action = db_session.get(Action, action.id)
    action.status = "retry_pending"
    action.next_attempt_at = datetime.now(timezone.utc)
    db_session.add(action)
    db_session.commit()
    service.execute_action(action.id)  # attempt 2 -> retry_pending

    action = db_session.get(Action, action.id)
    action.status = "retry_pending"
    action.next_attempt_at = datetime.now(timezone.utc)
    db_session.add(action)
    db_session.commit()
    result = service.execute_action(action.id)  # attempt 3 -> dead_letter
    db_session.expire_all()

    final_action = db_session.get(Action, action.id)
    refreshed_email = db_session.get(Email, email.id)

    assert result.status == "dead_letter"
    assert final_action.status == "dead_letter"
    assert final_action.next_attempt_at is None
    assert final_action.dead_lettered_at is not None
    assert refreshed_email.status == "action_failed"


def test_requeue_dead_letter_action(client, db_session):
    email = _create_classified_email(
        db_session,
        external_id="<inv-05@example.com>",
        sender="vendor@example.com",
        subject="Invoice #7783",
        body_text="Invoice #7783 amount $70.00",
        intent="invoice",
        confidence=0.95,
    )
    action = Action(
        email_id=email.id,
        intent="invoice",
        action_type="forward_to_accounting",
        status="dead_letter",
        payload={"entities": {"invoice_number": {"value_text": "7783"}, "amount": {"value_text": "$70.00"}}},
        attempts=3,
        dead_lettered_at=datetime.now(timezone.utc),
    )
    db_session.add(action)
    db_session.commit()

    list_response = client.get("/api/v1/actions/dead-letter?limit=20")
    list_payload = list_response.json()
    assert list_response.status_code == 200
    assert list_payload["count"] >= 1

    requeue_response = client.post(f"/api/v1/actions/{action.id}/requeue", json={"reset_attempts": True})
    requeue_payload = requeue_response.json()
    db_session.expire_all()

    refreshed = db_session.get(Action, action.id)
    assert requeue_response.status_code == 200
    assert requeue_payload["action"]["status"] == "retry_pending"
    assert refreshed.status == "retry_pending"
    assert refreshed.attempts == 0
    assert refreshed.dead_lettered_at is None


def test_idempotency_dispatch_prevents_duplicate_side_effects(db_session):
    email = _create_classified_email(
        db_session,
        external_id="<req-idempotent@example.com>",
        sender="ops@example.com",
        subject="Request: run task once",
        body_text="Please do this once.",
        intent="request",
        confidence=0.9,
    )
    action = Action(
        email_id=email.id,
        intent="request",
        action_type="create_task",
        status="pending",
        idempotency_key="plan-idempotency-test",
        payload={},
        attempts=0,
    )
    db_session.add(action)
    db_session.commit()

    service = ActionExecutionService(db_session)
    first = service.execute_action(action.id)
    db_session.expire_all()
    created_task_count = db_session.execute(select(Task).where(Task.email_id == email.id)).all()
    dispatches = list(db_session.scalars(select(ActionDispatch).where(ActionDispatch.action_id == action.id)))
    assert first.status == "executed"
    assert len(created_task_count) == 1
    assert len(dispatches) == 1

    # Simulate an external/manual incorrect requeue after a successful dispatch.
    action = db_session.get(Action, action.id)
    assert action is not None
    action.status = "retry_pending"
    action.next_attempt_at = datetime.now(timezone.utc)
    db_session.add(action)
    db_session.commit()

    second = service.execute_action(action.id)
    db_session.expire_all()
    second_task_count = db_session.execute(select(Task).where(Task.email_id == email.id)).all()
    assert second.status == "executed"
    assert len(second_task_count) == 1


def test_meeting_action_uses_google_calendar_client_when_enabled(db_session):
    class StubCalendarClient:
        def create_event(self, **kwargs):
            return {
                "id": "evt_123",
                "htmlLink": "https://calendar.google.com/event?eid=evt_123",
                "start": {"dateTime": kwargs["start_iso"]},
                "end": {"dateTime": kwargs["end_iso"]},
            }

    email = _create_classified_email(
        db_session,
        external_id="<meet-05@example.com>",
        sender="founder@example.com",
        subject="Meeting on 03/10/2026 at 10:30 am",
        body_text="Please schedule a meeting on 03/10/2026 at 10:30 am.",
        intent="meeting",
        confidence=0.9,
        entity_key="meeting_date",
        entity_value="03/10/2026",
    )
    db_session.add(
        Entity(
            email_id=email.id,
            entity_type="meeting",
            entity_key="meeting_time",
            value_text="10:30 am",
            value_json=None,
            confidence=0.9,
        )
    )
    action = Action(
        email_id=email.id,
        intent="meeting",
        action_type="schedule_calendar",
        status="pending",
        payload={"entities": {"meeting_date": {"value_text": "03/10/2026"}, "meeting_time": {"value_text": "10:30 am"}}},
        attempts=0,
    )
    db_session.add(action)
    db_session.commit()

    from app.config import get_settings

    settings = get_settings().model_copy(deep=True)
    settings.google_calendar_enabled = True
    settings.google_calendar_access_token = "fake-token"

    service = ActionExecutionService(db_session, settings=settings, calendar_client=StubCalendarClient())
    result = service.execute_action(action.id)
    db_session.expire_all()

    executed = db_session.get(Action, action.id)
    payload = executed.payload or {}
    output = payload.get("execution_output", {})

    assert result.status == "executed"
    assert executed.status == "executed"
    assert output.get("calendar_provider") == "google"
    assert output.get("event_id") == "evt_123"


def test_scheduled_action_jobs_plan_and_execute_pending_request(db_session):
    email = _create_classified_email(
        db_session,
        external_id="<req-04@example.com>",
        sender="pm@example.com",
        subject="Request: update roadmap",
        body_text="Please update roadmap by next week.",
        intent="request",
        confidence=0.93,
    )

    run_action_planning_job()
    action = db_session.execute(select(Action).where(Action.email_id == email.id)).scalar_one()
    action.status = "pending"
    db_session.add(action)
    db_session.commit()

    run_action_execution_job()
    db_session.expire_all()

    executed_action = db_session.get(Action, action.id)
    task = db_session.execute(select(Task).where(Task.email_id == email.id)).scalar_one()

    assert executed_action.status == "executed"
    assert task.title == "Request: update roadmap"


def test_action_events_endpoint_returns_timeline(client, db_session):
    email = _create_classified_email(
        db_session,
        external_id="<req-evt@example.com>",
        sender="ops@example.com",
        subject="Request: check audit events",
        body_text="Please create audit event sequence.",
        intent="request",
        confidence=0.9,
    )
    client.post("/api/v1/actions/plan", json={"limit": 10, "statuses": ["classified"]})
    action = db_session.execute(select(Action).where(Action.email_id == email.id)).scalar_one()
    client.post(f"/api/v1/actions/{action.id}/approve", json={"execute_now": True})

    response = client.get(f"/api/v1/actions/events?action_id={action.id}&limit=20")
    payload = response.json()
    event_types = {item["event_type"] for item in payload["items"]}

    assert response.status_code == 200
    assert payload["count"] >= 3
    assert {"planned", "approved", "executed"}.issubset(event_types)
