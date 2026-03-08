from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ActionPlanningBatchResult:
    matched: int
    planned: int
    skipped: int
    failed: int


@dataclass(slots=True)
class ActionExecutionBatchResult:
    matched: int
    executed: int
    failed: int


@dataclass(slots=True)
class ActionExecutionResult:
    status: str
    output: dict[str, Any] | None = None

