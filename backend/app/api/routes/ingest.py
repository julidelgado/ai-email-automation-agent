import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.observability import get_metrics_registry
from app.schemas.ingest import ImapPullRequest, ImapPullResponse
from app.services.ingest.service import EmailIngestionService

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/imap/pull", response_model=ImapPullResponse, status_code=status.HTTP_200_OK)
def pull_imap_messages(payload: ImapPullRequest, db: Session = Depends(get_db)) -> ImapPullResponse:
    started_at = time.perf_counter()
    metrics = get_metrics_registry()
    service = EmailIngestionService(db)
    try:
        result = service.ingest_from_imap(
            mailbox=payload.mailbox,
            unseen_only=payload.unseen_only,
            limit=payload.limit,
        )
    except ValueError as exc:
        metrics.record_job_run(
            job_name="imap_pull_manual",
            success=False,
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            error_message=str(exc),
            details={},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        metrics.record_job_run(
            job_name="imap_pull_manual",
            success=False,
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            error_message=str(exc),
            details={},
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        metrics.record_job_run(
            job_name="imap_pull_manual",
            success=False,
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            error_message=str(exc),
            details={},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error during IMAP ingestion.",
        ) from exc

    metrics.record_job_run(
        job_name="imap_pull_manual",
        success=True,
        duration_ms=(time.perf_counter() - started_at) * 1000.0,
        error_message=None,
        details={
            "fetched": result.fetched,
            "inserted": result.inserted,
            "duplicates": result.duplicates,
            "failed": result.failed,
        },
    )
    return ImapPullResponse(
        status="ok",
        mailbox=payload.mailbox,
        fetched=result.fetched,
        inserted=result.inserted,
        duplicates=result.duplicates,
        failed=result.failed,
    )
