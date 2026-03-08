from contextlib import asynccontextmanager
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request

from app.api.routes.dashboard import router as dashboard_router
from app.api.router import api_router
from app.config import get_settings
from app.observability import configure_logging, get_alert_service, get_metrics_registry
from app.security import build_basic_auth_middleware, validate_security_configuration
from app.workers.scheduler import SchedulerManager

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    validate_security_configuration(settings)
    scheduler_manager = SchedulerManager(settings=settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler_manager.start()
        try:
            yield
        finally:
            scheduler_manager.shutdown()

    app = FastAPI(
        title=settings.name,
        version="0.1.0",
        description="AI Email Automation Agent backend API.",
        lifespan=lifespan,
    )
    app.middleware("http")(build_basic_auth_middleware(settings))

    @app.middleware("http")
    async def request_observability_middleware(request: Request, call_next):
        metrics = get_metrics_registry()
        alerts = get_alert_service()
        started_at = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        method = request.method.upper()
        path = request.url.path

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - started_at) * 1000.0
            metrics.record_http_request(
                method=method,
                path=path,
                status_code=500,
                duration_ms=duration_ms,
                now_ts=time.time(),
            )
            logger.exception(
                "Unhandled request exception.",
                extra={
                    "event": "http_exception",
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            alerts.send_error_alert(
                title="Unhandled backend exception",
                message=str(exc),
                source="http.middleware",
                dedupe_key=f"http-exception:{method}:{path}",
                details={"method": method, "path": path, "request_id": request_id},
            )
            raise

        duration_ms = (time.perf_counter() - started_at) * 1000.0
        response.headers["X-Request-ID"] = request_id
        metrics.record_http_request(
            method=method,
            path=path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            now_ts=time.time(),
        )
        logger.info(
            "HTTP request completed.",
            extra={
                "event": "http_request",
                "request_id": request_id,
                "method": method,
                "path": path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "client": request.client.host if request.client else None,
            },
        )

        if response.status_code >= 500:
            alerts.send_error_alert(
                title="Backend returned HTTP 5xx",
                message=f"{method} {path} -> {response.status_code}",
                source="http.middleware",
                dedupe_key=f"http-5xx:{method}:{path}:{response.status_code}",
                details={"method": method, "path": path, "status_code": response.status_code, "request_id": request_id},
            )
        return response

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(dashboard_router)

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {
            "service": settings.name,
            "status": "ok",
            "version": "0.1.0",
        }

    return app


app = create_app()
