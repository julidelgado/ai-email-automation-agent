from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from email.message import EmailMessage
import logging
import smtplib
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.action import Action
from app.models.action_dispatch import ActionDispatch
from app.models.email import Email
from app.models.task import Task
from app.observability import get_alert_service, get_metrics_registry
from app.services.actions.audit import ActionAuditService
from app.services.actions.google_calendar_client import GoogleCalendarClient
from app.services.actions.types import ActionExecutionBatchResult, ActionExecutionResult

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"executed", "rejected", "dead_letter", "skipped"}
EXECUTABLE_STATUSES = {"pending", "retry_pending"}


class ActionExecutionService:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        calendar_client: GoogleCalendarClient | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.calendar_client = calendar_client or GoogleCalendarClient(self.settings, db=self.db)

    def approve_action(self, action_id: int, execute_now: bool) -> Action:
        action = self.db.get(Action, action_id)
        if not action:
            raise ValueError(f"Action {action_id} does not exist.")
        if action.status != "pending_approval":
            raise ValueError(f"Action {action_id} is not pending approval.")

        action.status = "pending"
        action.next_attempt_at = None
        action.error_message = None
        action.dead_lettered_at = None
        self.db.add(action)
        ActionAuditService.record_event(
            self.db,
            action_id=action.id,
            event_type="approved",
            status=action.status,
            message="Action approved for execution.",
            details={"execute_now": execute_now},
        )
        self.db.commit()

        if execute_now:
            self.execute_action(action.id)
            action = self.db.get(Action, action_id)
            if action is None:
                raise RuntimeError("Action disappeared during execution.")
        return action

    def reject_action(self, action_id: int, reason: str | None) -> Action:
        action = self.db.get(Action, action_id)
        if not action:
            raise ValueError(f"Action {action_id} does not exist.")
        if action.status in TERMINAL_STATUSES:
            raise ValueError(f"Action {action_id} is already terminal ({action.status}).")

        action.status = "rejected"
        action.error_message = (reason or "Rejected by reviewer.").strip()
        action.next_attempt_at = None
        action.executed_at = datetime.now(timezone.utc)
        action.dead_lettered_at = None
        self.db.add(action)
        ActionAuditService.record_event(
            self.db,
            action_id=action.id,
            event_type="rejected",
            status=action.status,
            message=action.error_message,
        )
        self._sync_email_status(action.email_id, latest_status=action.status)
        self.db.commit()
        return action

    def execute_pending_actions(self, limit: int, statuses: list[str] | None = None) -> ActionExecutionBatchResult:
        target_statuses = [status.strip() for status in (statuses or ["pending", "retry_pending"]) if status.strip()]
        if not target_statuses:
            target_statuses = ["pending", "retry_pending"]

        now_utc = datetime.now(timezone.utc)
        statement = (
            select(Action)
            .where(
                Action.status.in_(target_statuses),
                or_(Action.next_attempt_at.is_(None), Action.next_attempt_at <= now_utc),
            )
            .order_by(Action.next_attempt_at.is_(None), Action.next_attempt_at, Action.created_at, Action.id)
            .limit(limit)
        )
        actions = list(self.db.scalars(statement))

        executed = 0
        failed = 0
        for action in actions:
            result = self.execute_action(action.id)
            if result.status in {"executed", "skipped"}:
                executed += 1
            else:
                failed += 1

        return ActionExecutionBatchResult(matched=len(actions), executed=executed, failed=failed)

    def execute_action(self, action_id: int) -> ActionExecutionResult:
        metrics = get_metrics_registry()
        action = self.db.get(Action, action_id)
        if not action:
            raise ValueError(f"Action {action_id} does not exist.")
        if action.status not in EXECUTABLE_STATUSES:
            if action.status in {"executed", "skipped"}:
                metrics.record_action_result(action_type=action.action_type, status=action.status)
                return ActionExecutionResult(status=action.status, output=action.payload or {})
            raise ValueError(f"Action {action_id} cannot be executed from status {action.status}.")

        email = self.db.get(Email, action.email_id)
        if not email:
            raise RuntimeError(f"Email {action.email_id} not found for action {action.id}.")

        cached_dispatch = self._get_successful_dispatch(action)
        if cached_dispatch and action.action_type not in {"no_action", "manual_review"}:
            cached_output = cached_dispatch.output if isinstance(cached_dispatch.output, dict) else {}
            action.payload = self._merge_payload(action.payload, {"execution_output": cached_output})
            action.status = "executed"
            action.error_message = None
            action.next_attempt_at = None
            action.executed_at = datetime.now(timezone.utc)
            action.dead_lettered_at = None
            self.db.add(action)
            ActionAuditService.record_event(
                self.db,
                action_id=action.id,
                event_type="idempotency_hit",
                status=action.status,
                message="Execution skipped because idempotent dispatch record already exists.",
                details={"idempotency_key": cached_dispatch.idempotency_key},
            )
            self._sync_email_status(email.id, latest_status=action.status)
            self.db.commit()
            metrics.record_idempotency_hit(action_type=action.action_type)
            metrics.record_action_result(action_type=action.action_type, status=action.status)
            return ActionExecutionResult(status=action.status, output=cached_output)

        attempt_number = (action.attempts or 0) + 1
        action.attempts = attempt_number
        action.next_attempt_at = None
        action.dead_lettered_at = None
        self.db.add(action)

        try:
            ActionAuditService.record_event(
                self.db,
                action_id=action.id,
                event_type="execution_started",
                status=action.status,
                message="Action execution started.",
                details={"attempt": attempt_number},
            )
            execution_output = self._dispatch_execution(action, email)
            self._record_successful_dispatch(action=action, output=execution_output)
            action.payload = self._merge_payload(action.payload, {"execution_output": execution_output})
            action.status = "executed" if action.action_type not in {"no_action", "manual_review"} else "skipped"
            action.error_message = None
            action.executed_at = datetime.now(timezone.utc)
            action.next_attempt_at = None
            action.dead_lettered_at = None
            self.db.add(action)
            ActionAuditService.record_event(
                self.db,
                action_id=action.id,
                event_type="executed",
                status=action.status,
                message="Action executed successfully.",
                details={"attempt": attempt_number, "action_type": action.action_type},
            )
            self._sync_email_status(email.id, latest_status=action.status)
            self.db.commit()
            metrics.record_action_result(action_type=action.action_type, status=action.status)
            return ActionExecutionResult(status=action.status, output=execution_output)
        except Exception as exc:
            logger.exception("Action execution failed for action_id=%s", action.id)
            self.db.rollback()
            action = self.db.get(Action, action_id)
            if not action:
                raise RuntimeError("Action disappeared after rollback.") from exc
            action.attempts = attempt_number
            action.error_message = str(exc)
            if attempt_number < max(1, self.settings.action_max_attempts):
                delay_seconds = self._calculate_retry_delay_seconds(attempt_number)
                retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
                action.status = "retry_pending"
                action.next_attempt_at = retry_at
                action.dead_lettered_at = None
                message = f"Execution failed; retry scheduled in {delay_seconds} seconds."
                ActionAuditService.record_event(
                    self.db,
                    action_id=action.id,
                    event_type="retry_scheduled",
                    status=action.status,
                    message=message,
                    details={"attempt": attempt_number, "retry_at": retry_at.isoformat(), "error": str(exc)},
                )
            else:
                action.status = "dead_letter"
                action.next_attempt_at = None
                action.dead_lettered_at = datetime.now(timezone.utc)
                get_alert_service().send_error_alert(
                    title="Action moved to dead-letter queue",
                    message=f"Action #{action.id} reached retry limit.",
                    source="actions.executor",
                    dedupe_key=f"dead_letter:{action.id}",
                    details={
                        "action_id": action.id,
                        "action_type": action.action_type,
                        "intent": action.intent,
                        "attempt": attempt_number,
                        "max_attempts": self.settings.action_max_attempts,
                        "error": str(exc),
                    },
                )
                ActionAuditService.record_event(
                    self.db,
                    action_id=action.id,
                    event_type="dead_lettered",
                    status=action.status,
                    message="Action moved to dead-letter queue after retry limit reached.",
                    details={"attempt": attempt_number, "max_attempts": self.settings.action_max_attempts, "error": str(exc)},
                )
            self.db.add(action)
            self._sync_email_status(action.email_id, latest_status=action.status)
            self.db.commit()
            metrics.record_action_result(action_type=action.action_type, status=action.status)
            return ActionExecutionResult(status=action.status, output={"error": str(exc)})

    def list_dead_letter_actions(self, limit: int = 100) -> list[Action]:
        statement = (
            select(Action)
            .where(Action.status == "dead_letter")
            .order_by(Action.dead_lettered_at.desc(), Action.created_at.desc(), Action.id.desc())
            .limit(limit)
        )
        return list(self.db.scalars(statement))

    def requeue_dead_letter_action(self, action_id: int, *, reset_attempts: bool = False) -> Action:
        action = self.db.get(Action, action_id)
        if not action:
            raise ValueError(f"Action {action_id} does not exist.")
        if action.status != "dead_letter":
            raise ValueError(f"Action {action_id} is not in dead-letter queue.")

        action.status = "retry_pending"
        action.next_attempt_at = datetime.now(timezone.utc)
        action.error_message = None
        action.dead_lettered_at = None
        if reset_attempts:
            action.attempts = 0
        self.db.add(action)
        ActionAuditService.record_event(
            self.db,
            action_id=action.id,
            event_type="requeued",
            status=action.status,
            message="Action requeued from dead-letter queue.",
            details={"reset_attempts": reset_attempts},
        )
        self._sync_email_status(action.email_id, latest_status=action.status)
        self.db.commit()
        return action

    def _dispatch_execution(self, action: Action, email: Email) -> dict:
        action_type = (action.action_type or "").strip().lower()
        payload = action.payload or {}

        if action_type == "forward_to_accounting":
            return self._execute_invoice_forward(email=email, payload=payload)
        if action_type == "schedule_calendar":
            return self._execute_meeting_draft(email=email, payload=payload)
        if action_type == "create_task":
            return self._execute_task_creation(email=email, payload=payload)
        if action_type in {"no_action", "manual_review"}:
            return {"note": f"No external execution for action_type={action_type}."}

        raise RuntimeError(f"Unsupported action type: {action_type}")

    def _execute_invoice_forward(self, email: Email, payload: dict) -> dict:
        accounting_email = self.settings.action_invoice_accounting_email
        if not accounting_email:
            raise RuntimeError("APP_ACTION_INVOICE_ACCOUNTING_EMAIL is required for invoice forwarding.")
        if not self.settings.smtp_host:
            raise RuntimeError("APP_SMTP_HOST is required for invoice forwarding.")

        sender = self.settings.smtp_from_email or self.settings.smtp_username
        if not sender:
            raise RuntimeError("SMTP sender is not configured. Set APP_SMTP_FROM_EMAIL or APP_SMTP_USERNAME.")

        invoice_number = _entity_value(payload, "invoice_number")
        amount = _entity_value(payload, "amount")

        message = EmailMessage()
        message["From"] = sender
        message["To"] = accounting_email
        message["Subject"] = f"[Invoice] {email.subject or '(no subject)'}"
        message.set_content(
            "\n".join(
                [
                    "Forwarded invoice message.",
                    f"Original sender: {email.sender}",
                    f"Original subject: {email.subject or '(no subject)'}",
                    f"Invoice number: {invoice_number or 'unknown'}",
                    f"Amount: {amount or 'unknown'}",
                    "",
                    "Body preview:",
                    (email.body_text or email.body_html or "")[:1200],
                ]
            )
        )

        smtp = smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20)
        try:
            if self.settings.smtp_use_tls:
                smtp.starttls()
            if self.settings.smtp_username and self.settings.smtp_password:
                smtp.login(self.settings.smtp_username, self.settings.smtp_password)
            smtp.send_message(message)
        finally:
            smtp.quit()

        return {
            "forwarded_to": accounting_email,
            "invoice_number": invoice_number,
            "amount": amount,
            "method": "smtp",
        }

    def _execute_meeting_draft(self, email: Email, payload: dict) -> dict:
        start_dt, end_dt = _resolve_meeting_window(
            payload=payload,
            duration_minutes=self.settings.action_meeting_default_duration_minutes,
            timezone_name=self.settings.action_calendar_timezone,
        )
        summary = email.subject or "Meeting"
        description = (
            f"Email sender: {email.sender}\n\n"
            f"Subject: {email.subject or '(no subject)'}\n\n"
            f"Body preview:\n{(email.body_text or email.body_html or '')[:1200]}"
        )

        if self.settings.google_calendar_enabled:
            event = self.calendar_client.create_event(
                summary=summary,
                description=description,
                start_iso=start_dt.isoformat(),
                end_iso=end_dt.isoformat(),
                timezone_name=self.settings.action_calendar_timezone,
            )
            return {
                "calendar_provider": "google",
                "calendar_id": self.settings.google_calendar_calendar_id,
                "event_id": event.get("id"),
                "event_link": event.get("htmlLink"),
                "start": event.get("start"),
                "end": event.get("end"),
            }

        meeting_date = _entity_value(payload, "meeting_date")
        meeting_time = _entity_value(payload, "meeting_time")
        duration_minutes = self.settings.action_meeting_default_duration_minutes

        return {
            "calendar_draft": {
                "title": email.subject or "Meeting",
                "organizer": email.sender,
                "date": meeting_date,
                "time": meeting_time,
                "duration_minutes": duration_minutes,
                "notes_preview": (email.body_text or email.body_html or "")[:400],
            },
            "calendar_provider": "draft",
            "reason": "Google Calendar integration disabled.",
        }

    def _execute_task_creation(self, email: Email, payload: dict) -> dict:
        summary = _entity_value(payload, "task_summary") or email.subject or "Request task"
        deadline = _entity_value(payload, "deadline")
        task = Task(
            email_id=email.id,
            title=summary[:255],
            description=(email.body_text or email.body_html or "")[:4000] or None,
            due_text=deadline[:255] if isinstance(deadline, str) else None,
            status="open",
        )
        self.db.add(task)
        self.db.flush()
        return {
            "task_id": task.id,
            "title": task.title,
            "due_text": task.due_text,
        }

    def _sync_email_status(self, email_id: int, latest_status: str | None = None) -> None:
        email = self.db.get(Email, email_id)
        if not email:
            return

        resolved_status = latest_status
        if resolved_status is None:
            statement = (
                select(Action.status).where(Action.email_id == email_id).order_by(Action.created_at.desc(), Action.id.desc())
            )
            resolved_status = self.db.execute(statement).scalar_one_or_none()
        if resolved_status == "pending_approval":
            email.status = "action_pending_approval"
        elif resolved_status == "pending":
            email.status = "action_pending"
        elif resolved_status == "retry_pending":
            email.status = "action_retry_pending"
        elif resolved_status in {"executed", "skipped"}:
            email.status = "action_executed"
        elif resolved_status == "dead_letter":
            email.status = "action_failed"
        elif resolved_status == "rejected":
            email.status = "action_rejected"

        self.db.add(email)

    @staticmethod
    def _merge_payload(existing_payload, updates: dict) -> dict:
        merged: dict = {}
        if isinstance(existing_payload, dict):
            merged.update(existing_payload)
        merged.update(updates)
        return merged

    def _calculate_retry_delay_seconds(self, attempt_number: int) -> int:
        base = max(1, self.settings.action_retry_base_seconds)
        max_delay = max(base, self.settings.action_retry_max_seconds)
        exponent = max(0, attempt_number - 1)
        delay = base * (2**exponent)
        return min(delay, max_delay)

    def _get_successful_dispatch(self, action: Action) -> ActionDispatch | None:
        key = self._dispatch_idempotency_key(action)
        statement = (
            select(ActionDispatch)
            .where(
                ActionDispatch.idempotency_key == key,
                ActionDispatch.dispatch_status == "succeeded",
            )
            .limit(1)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def _record_successful_dispatch(self, *, action: Action, output: dict) -> None:
        key = self._dispatch_idempotency_key(action)
        statement = select(ActionDispatch).where(ActionDispatch.idempotency_key == key).limit(1)
        record = self.db.execute(statement).scalar_one_or_none()
        if record is None:
            record = ActionDispatch(
                action_id=action.id,
                idempotency_key=key,
                dispatch_status="succeeded",
            )
        record.dispatch_status = "succeeded"
        record.output = output
        record.error_message = None
        self.db.add(record)

    @staticmethod
    def _dispatch_idempotency_key(action: Action) -> str:
        base = (action.idempotency_key or f"legacy-action-{action.id}").strip()
        key = f"dispatch-{base}"
        return key[:128]


def _entity_value(payload: dict, key: str):
    entities = payload.get("entities")
    if not isinstance(entities, dict):
        return None
    item = entities.get(key)
    if not isinstance(item, dict):
        return None
    value_text = item.get("value_text")
    if value_text is not None:
        return value_text
    return item.get("value_json")


def _resolve_meeting_window(payload: dict, duration_minutes: int, timezone_name: str) -> tuple[datetime, datetime]:
    tz = _safe_timezone(timezone_name)
    meeting_date = _as_text(_entity_value(payload, "meeting_date"))
    meeting_time = _as_text(_entity_value(payload, "meeting_time"))

    start_dt = _parse_meeting_datetime(meeting_date, meeting_time, tz)
    end_dt = start_dt + timedelta(minutes=max(5, duration_minutes))
    return start_dt, end_dt


def _parse_meeting_datetime(meeting_date: str | None, meeting_time: str | None, tz: ZoneInfo) -> datetime:
    date_value = _parse_date(meeting_date)
    if date_value is None:
        date_value = (datetime.now(tz) + timedelta(days=1)).date()

    time_value = _parse_time(meeting_time)
    if time_value is None:
        time_value = time(hour=9, minute=0)

    return datetime.combine(date_value, time_value, tzinfo=tz)


def _parse_date(value: str | None):
    if not value:
        return None
    cleaned = value.strip().replace(",", "")
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%m-%d-%Y",
        "%d-%m-%Y",
        "%b %d %Y",
        "%B %d %Y",
        "%b %d %y",
        "%B %d %y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(value: str | None):
    if not value:
        return None
    cleaned = value.strip().lower().replace(".", "")
    formats = [
        "%H:%M",
        "%I:%M %p",
        "%I %p",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).time()
        except ValueError:
            continue
    return None


def _safe_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def _as_text(value) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned if cleaned else None
    return None
