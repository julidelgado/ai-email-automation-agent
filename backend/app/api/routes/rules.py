from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.rule import Rule
from app.schemas.rules import (
    RuleBulkUpdateRequest,
    RuleBulkUpdateResponse,
    RuleItem,
    RuleListResponse,
    RuleMutationResponse,
    RuleUpdateRequest,
)
from app.services.routing.default_rules import ensure_default_rules

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("", response_model=RuleListResponse, status_code=status.HTTP_200_OK)
def list_rules(db: Session = Depends(get_db)) -> RuleListResponse:
    ensure_default_rules(db)
    statement = select(Rule).order_by(Rule.intent.asc())
    rules = list(db.scalars(statement))
    items = [_to_rule_item(rule) for rule in rules]
    return RuleListResponse(items=items, count=len(items))


@router.patch("/bulk", response_model=RuleBulkUpdateResponse, status_code=status.HTTP_200_OK)
def bulk_update_rules(payload: RuleBulkUpdateRequest, db: Session = Depends(get_db)) -> RuleBulkUpdateResponse:
    ensure_default_rules(db)

    rule_ids = [item.id for item in payload.rules]
    if len(set(rule_ids)) != len(rule_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate rule IDs in bulk payload.")

    statement = select(Rule).where(Rule.id.in_(rule_ids))
    found_rules = list(db.scalars(statement))
    rule_map = {rule.id: rule for rule in found_rules}

    missing = [rule_id for rule_id in rule_ids if rule_id not in rule_map]
    if missing:
        missing_csv = ", ".join(str(item) for item in missing)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Rules not found: {missing_csv}.")

    for item in payload.rules:
        rule = rule_map[item.id]
        _apply_rule_update(rule, item.min_confidence, item.requires_approval, item.is_active)
        db.add(rule)

    db.commit()

    reloaded_statement = select(Rule).where(Rule.id.in_(rule_ids)).order_by(Rule.intent.asc())
    reloaded = list(db.scalars(reloaded_statement))
    items = [_to_rule_item(rule) for rule in reloaded]
    return RuleBulkUpdateResponse(status="ok", updated_count=len(items), rules=items)


@router.patch("/{rule_id}", response_model=RuleMutationResponse, status_code=status.HTTP_200_OK)
def update_rule(
    rule_id: int,
    payload: RuleUpdateRequest,
    db: Session = Depends(get_db),
) -> RuleMutationResponse:
    ensure_default_rules(db)
    rule = db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Rule {rule_id} not found.")

    _apply_rule_update(rule, payload.min_confidence, payload.requires_approval, payload.is_active)
    db.add(rule)
    db.commit()
    db.refresh(rule)

    return RuleMutationResponse(status="ok", rule=_to_rule_item(rule))


def _to_rule_item(rule: Rule) -> RuleItem:
    return RuleItem(
        id=rule.id,
        intent=rule.intent,
        action_type=rule.action_type,
        min_confidence=rule.min_confidence,
        requires_approval=rule.requires_approval,
        is_active=rule.is_active,
        description=rule.description,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _apply_rule_update(rule: Rule, min_confidence: float, requires_approval: bool, is_active: bool) -> None:
    rule.min_confidence = min_confidence
    rule.requires_approval = requires_approval
    rule.is_active = is_active
