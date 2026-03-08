from __future__ import annotations

from datetime import datetime, timezone

from app.models.email import Email
from app.models.task import Task


def _seed_task(db_session, *, external_id: str, title: str, status: str, due_text: str | None) -> Task:
    email = Email(
        external_id=external_id,
        sender="tester@example.com",
        subject=title,
        body_text="Task source email",
        received_at=datetime(2026, 3, 10, 9, 30, tzinfo=timezone.utc),
        status="action_executed",
    )
    db_session.add(email)
    db_session.flush()

    task = Task(
        email_id=email.id,
        title=title,
        description=f"Description for {title}",
        due_text=due_text,
        status=status,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


def test_list_tasks_returns_created_tasks(client, db_session):
    _seed_task(
        db_session,
        external_id="<task-01@example.com>",
        title="Prepare weekly report",
        status="open",
        due_text="March 15, 2026",
    )
    _seed_task(
        db_session,
        external_id="<task-02@example.com>",
        title="Follow up with finance",
        status="done",
        due_text=None,
    )

    response = client.get("/api/v1/tasks?limit=20")
    payload = response.json()

    assert response.status_code == 200
    assert payload["count"] == 2
    titles = [item["title"] for item in payload["items"]]
    assert "Prepare weekly report" in titles
    assert "Follow up with finance" in titles


def test_list_tasks_status_filter(client, db_session):
    _seed_task(
        db_session,
        external_id="<task-03@example.com>",
        title="Create release summary",
        status="open",
        due_text="March 20, 2026",
    )
    _seed_task(
        db_session,
        external_id="<task-04@example.com>",
        title="Archive old items",
        status="done",
        due_text=None,
    )

    response = client.get("/api/v1/tasks?status=open&limit=20")
    payload = response.json()

    assert response.status_code == 200
    assert payload["count"] == 1
    assert payload["items"][0]["title"] == "Create release summary"
    assert payload["items"][0]["status"] == "open"

