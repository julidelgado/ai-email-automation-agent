from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ExtractedEntity:
    entity_type: str
    entity_key: str
    value_text: str | None = None
    value_json: dict[str, Any] | list[Any] | None = None
    confidence: float | None = None


@dataclass(slots=True)
class ClassificationOutput:
    intent: str
    confidence: float
    rationale: str | None
    entities: list[ExtractedEntity] = field(default_factory=list)
    model_name: str = "rule_based"
    model_version: str | None = "1.0"


@dataclass(slots=True)
class ClassificationBatchResult:
    matched: int
    processed: int
    failed: int

