import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.observability import get_metrics_registry
from app.schemas.pipeline import ClassifyPendingRequest, ClassifyPendingResponse
from app.services.ai.pipeline import ClassificationPipelineService

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/classify", response_model=ClassifyPendingResponse, status_code=status.HTTP_200_OK)
def classify_pending_emails(
    payload: ClassifyPendingRequest,
    db: Session = Depends(get_db),
) -> ClassifyPendingResponse:
    started_at = time.perf_counter()
    metrics = get_metrics_registry()
    service = ClassificationPipelineService(db)
    try:
        result = service.process_pending_emails(limit=payload.limit, statuses=payload.statuses)
    except Exception as exc:
        metrics.record_job_run(
            job_name="classification_manual",
            success=False,
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            error_message=str(exc),
            details={},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error during classification pipeline execution.",
        ) from exc

    metrics.record_job_run(
        job_name="classification_manual",
        success=True,
        duration_ms=(time.perf_counter() - started_at) * 1000.0,
        error_message=None,
        details={"matched": result.matched, "processed": result.processed, "failed": result.failed},
    )
    return ClassifyPendingResponse(
        status="ok",
        matched=result.matched,
        processed=result.processed,
        failed=result.failed,
    )
