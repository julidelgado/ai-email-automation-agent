from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.name,
        environment=settings.environment,
    )


@router.get("/ready", response_model=ReadinessResponse, status_code=status.HTTP_200_OK)
def readiness_check(response: Response, db: Session = Depends(get_db)) -> ReadinessResponse:
    checks: dict[str, str] = {}
    status_value = "ready"

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
        status_value = "not_ready"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(status=status_value, checks=checks)

