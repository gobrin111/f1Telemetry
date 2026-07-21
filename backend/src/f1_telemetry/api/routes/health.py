"""Service health endpoint."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from f1_telemetry.core.config import Settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Response returned when the API process is healthy."""

    status: Literal["ok"]
    service: Literal["api"]
    environment: str


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Confirm that the API process is accepting requests."""
    settings: Settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service="api",
        environment=settings.environment,
    )
