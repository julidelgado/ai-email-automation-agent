from fastapi import APIRouter

from app.api.routes.actions import router as actions_router
from app.api.routes.health import router as health_router
from app.api.routes.ingest import router as ingest_router
from app.api.routes.integrations import router as integrations_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.pipeline import router as pipeline_router
from app.api.routes.rules import router as rules_router
from app.api.routes.tasks import router as tasks_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(ingest_router)
api_router.include_router(pipeline_router)
api_router.include_router(actions_router)
api_router.include_router(rules_router)
api_router.include_router(integrations_router)
api_router.include_router(tasks_router)
api_router.include_router(metrics_router)
