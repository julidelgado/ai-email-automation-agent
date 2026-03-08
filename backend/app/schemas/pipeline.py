from pydantic import BaseModel, Field


class ClassifyPendingRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=200)
    statuses: list[str] = Field(default_factory=lambda: ["new"])


class ClassifyPendingResponse(BaseModel):
    status: str
    matched: int
    processed: int
    failed: int

