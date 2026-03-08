from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.action import Action
from app.models.action_event import ActionEvent
from app.schemas.actions import (
    ActionApprovalRequest,
    ActionEventItem,
    ActionEventListResponse,
    ActionExecuteRequest,
    ActionExecuteResponse,
    ActionItem,
    ActionListResponse,
    ActionMutationResponse,
    ActionPlanRequest,
    ActionPlanResponse,
    ActionRequeueRequest,
    ActionRejectRequest,
)
from app.observability import get_metrics_registry
from app.services.actions.executor import ActionExecutionService
from app.services.actions.planner import ActionPlanningService

router = APIRouter(prefix="/actions", tags=["actions"])


@router.post("/plan", response_model=ActionPlanResponse, status_code=status.HTTP_200_OK)
def plan_actions(payload: ActionPlanRequest, db: Session = Depends(get_db)) -> ActionPlanResponse:
    started_at = time.perf_counter()
    metrics = get_metrics_registry()
    service = ActionPlanningService(db)
    try:
        result = service.plan_for_classified_emails(limit=payload.limit, statuses=payload.statuses)
    except Exception as exc:
        metrics.record_job_run(
            job_name="action_planning_manual",
            success=False,
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            error_message=str(exc),
            details={},
        )
        raise
    metrics.record_job_run(
        job_name="action_planning_manual",
        success=True,
        duration_ms=(time.perf_counter() - started_at) * 1000.0,
        error_message=None,
        details={"matched": result.matched, "planned": result.planned, "skipped": result.skipped, "failed": result.failed},
    )
    return ActionPlanResponse(
        status="ok",
        matched=result.matched,
        planned=result.planned,
        skipped=result.skipped,
        failed=result.failed,
    )


@router.get("", response_model=ActionListResponse, status_code=status.HTTP_200_OK)
def list_actions(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ActionListResponse:
    statement = select(Action).order_by(Action.created_at.desc(), Action.id.desc()).limit(limit)
    if status_filter:
        statement = statement.where(Action.status == status_filter)

    actions = list(db.scalars(statement))
    items = [_to_action_item(action) for action in actions]
    return ActionListResponse(items=items, count=len(items))


@router.post("/execute", response_model=ActionExecuteResponse, status_code=status.HTTP_200_OK)
def execute_actions(payload: ActionExecuteRequest, db: Session = Depends(get_db)) -> ActionExecuteResponse:
    started_at = time.perf_counter()
    metrics = get_metrics_registry()
    service = ActionExecutionService(db)
    try:
        result = service.execute_pending_actions(limit=payload.limit, statuses=payload.statuses)
    except Exception as exc:
        metrics.record_job_run(
            job_name="action_execution_manual",
            success=False,
            duration_ms=(time.perf_counter() - started_at) * 1000.0,
            error_message=str(exc),
            details={},
        )
        raise
    metrics.record_job_run(
        job_name="action_execution_manual",
        success=True,
        duration_ms=(time.perf_counter() - started_at) * 1000.0,
        error_message=None,
        details={"matched": result.matched, "executed": result.executed, "failed": result.failed},
    )
    return ActionExecuteResponse(status="ok", matched=result.matched, executed=result.executed, failed=result.failed)


@router.get("/dead-letter", response_model=ActionListResponse, status_code=status.HTTP_200_OK)
def list_dead_letter_actions(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> ActionListResponse:
    service = ActionExecutionService(db)
    actions = service.list_dead_letter_actions(limit=limit)
    items = [_to_action_item(action) for action in actions]
    return ActionListResponse(items=items, count=len(items))


@router.post("/{action_id}/requeue", response_model=ActionMutationResponse, status_code=status.HTTP_200_OK)
def requeue_dead_letter_action(
    action_id: int,
    payload: ActionRequeueRequest,
    db: Session = Depends(get_db),
) -> ActionMutationResponse:
    service = ActionExecutionService(db)
    try:
        action = service.requeue_dead_letter_action(action_id=action_id, reset_attempts=payload.reset_attempts)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return ActionMutationResponse(status="ok", action=_to_action_item(action))


@router.post("/{action_id}/approve", response_model=ActionMutationResponse, status_code=status.HTTP_200_OK)
def approve_action(
    action_id: int,
    payload: ActionApprovalRequest,
    db: Session = Depends(get_db),
) -> ActionMutationResponse:
    service = ActionExecutionService(db)
    try:
        action = service.approve_action(action_id=action_id, execute_now=payload.execute_now)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return ActionMutationResponse(status="ok", action=_to_action_item(action))


@router.post("/{action_id}/reject", response_model=ActionMutationResponse, status_code=status.HTTP_200_OK)
def reject_action(
    action_id: int,
    payload: ActionRejectRequest,
    db: Session = Depends(get_db),
) -> ActionMutationResponse:
    service = ActionExecutionService(db)
    try:
        action = service.reject_action(action_id=action_id, reason=payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return ActionMutationResponse(status="ok", action=_to_action_item(action))


@router.post("/{action_id}/execute", response_model=ActionMutationResponse, status_code=status.HTTP_200_OK)
def execute_action(action_id: int, db: Session = Depends(get_db)) -> ActionMutationResponse:
    service = ActionExecutionService(db)
    try:
        service.execute_action(action_id=action_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    action = db.get(Action, action_id)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Action {action_id} not found.")
    return ActionMutationResponse(status="ok", action=_to_action_item(action))


@router.get("/events", response_model=ActionEventListResponse, status_code=status.HTTP_200_OK)
def list_action_events(
    action_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> ActionEventListResponse:
    statement = select(ActionEvent).order_by(ActionEvent.created_at.desc(), ActionEvent.id.desc()).limit(limit)
    if action_id is not None:
        statement = statement.where(ActionEvent.action_id == action_id)

    events = list(db.scalars(statement))
    items = [
        ActionEventItem(
            id=event.id,
            action_id=event.action_id,
            event_type=event.event_type,
            status=event.status,
            message=event.message,
            details=event.details,
            created_at=event.created_at,
        )
        for event in events
    ]
    return ActionEventListResponse(items=items, count=len(items))


def _to_action_item(action: Action) -> ActionItem:
    return ActionItem(
        id=action.id,
        email_id=action.email_id,
        intent=action.intent,
        action_type=action.action_type,
        status=action.status,
        idempotency_key=action.idempotency_key,
        attempts=action.attempts,
        next_attempt_at=action.next_attempt_at,
        error_message=action.error_message,
        created_at=action.created_at,
        executed_at=action.executed_at,
        dead_lettered_at=action.dead_lettered_at,
        payload=action.payload,
    )
