"""Minimal API for queuing and tracking FastF1 imports."""

from fastapi import APIRouter, HTTPException, Request, status
from redis import Redis

from f1_telemetry.core.config import Settings
from f1_telemetry.ingestion.jobs import (
    ImportJobNotFoundError,
    enqueue_session_import,
    get_session_import,
)
from f1_telemetry.ingestion.models import SessionImportJob, SessionImportRequest

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("", response_model=SessionImportJob, status_code=status.HTTP_202_ACCEPTED)
async def create_import(
    payload: SessionImportRequest,
    request: Request,
) -> SessionImportJob:
    """Queue one completed race import or return its existing state."""
    settings: Settings = request.app.state.settings
    connection: Redis = request.app.state.redis
    return enqueue_session_import(
        payload,
        settings=settings,
        connection=connection,
    )


@router.get("/{job_id}", response_model=SessionImportJob)
async def import_status(job_id: str, request: Request) -> SessionImportJob:
    """Return progress, completion, or a safe failure message for an import."""
    connection: Redis = request.app.state.redis
    try:
        return get_session_import(job_id, connection=connection)
    except ImportJobNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import job not found",
        ) from error
