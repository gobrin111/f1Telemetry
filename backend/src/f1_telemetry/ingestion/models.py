"""API models for session import jobs."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ImportStatus = Literal[
    "created",
    "queued",
    "started",
    "finished",
    "failed",
    "deferred",
    "scheduled",
    "stopped",
    "canceled",
]


class SessionImportRequest(BaseModel):
    """Request to import one completed Formula 1 race."""

    year: int = Field(ge=2018)
    round_number: int = Field(ge=1, le=30)
    retry_failed: bool = False

    @field_validator("year")
    @classmethod
    def year_cannot_be_in_the_future(cls, value: int) -> int:
        if value > datetime.now(UTC).year:
            raise ValueError("year cannot be in the future")
        return value


class SessionImportJob(BaseModel):
    """Public state for one deterministic session import."""

    id: str
    session_key: str
    year: int
    round_number: int
    session: Literal["R"] = "R"
    status: ImportStatus
    progress: int = Field(ge=0, le=100)
    stage: str
    message: str | None = None
    error: str | None = None
    artifact_key: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
