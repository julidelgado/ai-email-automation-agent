from __future__ import annotations

import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import Settings, get_settings
from app.db.session import get_session_factory
from app.observability import get_alert_service, get_metrics_registry
from app.services.actions.executor import ActionExecutionService
from app.services.actions.planner import ActionPlanningService
from app.services.ai.pipeline import ClassificationPipelineService
from app.services.ingest.service import EmailIngestionService
from app.services.routing.default_rules import ensure_default_rules

logger = logging.getLogger(__name__)


def run_imap_pull_job() -> None:
    settings = get_settings()
    started_at = time.perf_counter()
    if not _is_imap_configured(settings):
        logger.debug("Skipping scheduled IMAP pull because credentials are not configured.")
        _record_job_success(
            job_name="imap_pull",
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            details={"skipped": True, "reason": "imap_not_configured"},
        )
        return

    db = get_session_factory()()
    try:
        service = EmailIngestionService(db)
        result = service.ingest_from_imap(
            mailbox=settings.imap_default_mailbox,
            unseen_only=settings.imap_pull_unseen_only,
            limit=settings.imap_pull_limit,
        )
        logger.info(
            "Scheduled IMAP pull finished: fetched=%s inserted=%s duplicates=%s failed=%s",
            result.fetched,
            result.inserted,
            result.duplicates,
            result.failed,
        )
        _record_job_success(
            job_name="imap_pull",
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            details={
                "fetched": result.fetched,
                "inserted": result.inserted,
                "duplicates": result.duplicates,
                "failed": result.failed,
            },
        )
    except Exception as exc:
        logger.exception("Scheduled IMAP pull failed.")
        _record_job_failure(
            job_name="imap_pull",
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            error_message=str(exc),
        )
    finally:
        db.close()


def run_classification_job() -> None:
    settings = get_settings()
    started_at = time.perf_counter()
    db = get_session_factory()()
    try:
        service = ClassificationPipelineService(db, settings=settings)
        result = service.process_pending_emails(limit=settings.classify_batch_size, statuses=["new"])
        logger.info(
            "Scheduled classification finished: matched=%s processed=%s failed=%s",
            result.matched,
            result.processed,
            result.failed,
        )
        _record_job_success(
            job_name="classification",
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            details={"matched": result.matched, "processed": result.processed, "failed": result.failed},
        )
    except Exception as exc:
        logger.exception("Scheduled classification failed.")
        _record_job_failure(
            job_name="classification",
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            error_message=str(exc),
        )
    finally:
        db.close()


def run_action_planning_job() -> None:
    settings = get_settings()
    started_at = time.perf_counter()
    db = get_session_factory()()
    try:
        service = ActionPlanningService(db)
        result = service.plan_for_classified_emails(limit=settings.action_plan_batch_size, statuses=["classified"])
        logger.info(
            "Scheduled action planning finished: matched=%s planned=%s skipped=%s failed=%s",
            result.matched,
            result.planned,
            result.skipped,
            result.failed,
        )
        _record_job_success(
            job_name="action_planning",
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            details={
                "matched": result.matched,
                "planned": result.planned,
                "skipped": result.skipped,
                "failed": result.failed,
            },
        )
    except Exception as exc:
        logger.exception("Scheduled action planning failed.")
        _record_job_failure(
            job_name="action_planning",
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            error_message=str(exc),
        )
    finally:
        db.close()


def run_action_execution_job() -> None:
    settings = get_settings()
    started_at = time.perf_counter()
    db = get_session_factory()()
    try:
        service = ActionExecutionService(db, settings=settings)
        result = service.execute_pending_actions(
            limit=settings.action_execution_batch_size,
            statuses=["pending", "retry_pending"],
        )
        logger.info(
            "Scheduled action execution finished: matched=%s executed=%s failed=%s",
            result.matched,
            result.executed,
            result.failed,
        )
        _record_job_success(
            job_name="action_execution",
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            details={"matched": result.matched, "executed": result.executed, "failed": result.failed},
        )
    except Exception as exc:
        logger.exception("Scheduled action execution failed.")
        _record_job_failure(
            job_name="action_execution",
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            error_message=str(exc),
        )
    finally:
        db.close()


class SchedulerManager:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.scheduler: BackgroundScheduler | None = None

    def start(self) -> None:
        if not self.settings.scheduler_enabled:
            logger.info("Scheduler is disabled by configuration.")
            return
        if self.scheduler and self.scheduler.running:
            return

        self._ensure_bootstrap_data()
        self.scheduler = BackgroundScheduler(timezone=self.settings.scheduler_timezone)
        self.scheduler.add_job(
            run_imap_pull_job,
            trigger="interval",
            minutes=max(1, self.settings.imap_pull_interval_minutes),
            id="imap_pull_job",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
            misfire_grace_time=30,
        )
        self.scheduler.add_job(
            run_classification_job,
            trigger="interval",
            minutes=max(1, self.settings.classify_interval_minutes),
            id="classification_job",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
            misfire_grace_time=30,
        )
        self.scheduler.add_job(
            run_action_planning_job,
            trigger="interval",
            minutes=max(1, self.settings.action_plan_interval_minutes),
            id="action_planning_job",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
            misfire_grace_time=30,
        )
        self.scheduler.add_job(
            run_action_execution_job,
            trigger="interval",
            minutes=max(1, self.settings.action_execution_interval_minutes),
            id="action_execution_job",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
            misfire_grace_time=30,
        )
        self.scheduler.start()
        logger.info("Scheduler started with %s jobs.", len(self.scheduler.get_jobs()))

    def shutdown(self) -> None:
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped.")

    @staticmethod
    def _ensure_bootstrap_data() -> None:
        db = get_session_factory()()
        try:
            ensure_default_rules(db)
        finally:
            db.close()


def _is_imap_configured(settings: Settings) -> bool:
    return bool(settings.imap_host and settings.imap_username and settings.imap_password)


def _record_job_success(*, job_name: str, duration_ms: float, details: dict) -> None:
    get_metrics_registry().record_job_run(
        job_name=job_name,
        success=True,
        duration_ms=duration_ms,
        details=details,
    )


def _record_job_failure(*, job_name: str, duration_ms: float, error_message: str) -> None:
    metrics = get_metrics_registry()
    metrics.record_job_run(
        job_name=job_name,
        success=False,
        duration_ms=duration_ms,
        details={},
        error_message=error_message,
    )
    get_alert_service().send_error_alert(
        title=f"Scheduled job failed: {job_name}",
        message=error_message,
        source="scheduler",
        dedupe_key=f"scheduler:{job_name}",
        details={"job_name": job_name},
    )
