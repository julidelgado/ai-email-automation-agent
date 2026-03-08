from pydantic import BaseModel, Field


class ImapPullRequest(BaseModel):
    mailbox: str = Field(default="INBOX", min_length=1, max_length=128)
    unseen_only: bool = True
    limit: int = Field(default=25, ge=1, le=200)


class ImapPullResponse(BaseModel):
    status: str
    mailbox: str
    fetched: int
    inserted: int
    duplicates: int
    failed: int

