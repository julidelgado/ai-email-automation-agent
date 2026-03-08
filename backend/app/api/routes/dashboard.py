from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(tags=["dashboard"])

_DASHBOARD_FILE = Path(__file__).resolve().parents[2] / "templates" / "dashboard.html"
_METRICS_FILE = Path(__file__).resolve().parents[2] / "templates" / "metrics.html"


@router.get("/dashboard", response_class=FileResponse)
def get_dashboard() -> FileResponse:
    if not _DASHBOARD_FILE.exists():
        raise HTTPException(status_code=500, detail="Dashboard file is missing.")
    return FileResponse(_DASHBOARD_FILE, media_type="text/html")


@router.get("/metrics", response_class=FileResponse)
def get_metrics_dashboard() -> FileResponse:
    if not _METRICS_FILE.exists():
        raise HTTPException(status_code=500, detail="Metrics dashboard file is missing.")
    return FileResponse(_METRICS_FILE, media_type="text/html")
