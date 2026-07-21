"""Redis Queue orchestration for FastF1 session imports."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from redis import Redis
from rq import Queue, get_current_job
from rq.exceptions import NoSuchJobError
from rq.job import Job, JobStatus

from f1_telemetry.core.config import Settings, get_settings
from f1_telemetry.ingestion.importer import (
    import_race_session,
    manifest_path,
    read_manifest,
    session_key,
)
from f1_telemetry.ingestion.models import SessionImportJob, SessionImportRequest
from f1_telemetry.storage.persistence import (
    is_session_persisted,
    persist_session_artifacts,
)


class ImportJobNotFoundError(LookupError):
    """Raised when a requested import job no longer exists."""


def _job_id(year: int, round_number: int) -> str:
    return f"import-{session_key(year, round_number)}"


def _datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _job_response(job: Job) -> SessionImportJob:
    status = job.get_status(refresh=True)
    progress_defaults = {
        JobStatus.CREATED: 0,
        JobStatus.QUEUED: 0,
        JobStatus.STARTED: 1,
        JobStatus.FINISHED: 100,
        JobStatus.FAILED: 0,
        JobStatus.DEFERRED: 0,
        JobStatus.SCHEDULED: 0,
        JobStatus.STOPPED: 0,
        JobStatus.CANCELED: 0,
    }
    return SessionImportJob(
        id=job.id,
        session_key=str(job.meta["session_key"]),
        year=int(job.meta["year"]),
        round_number=int(job.meta["round_number"]),
        status=status.value,
        progress=int(job.meta.get("progress", progress_defaults[status])),
        stage=str(job.meta.get("stage", status.value)),
        message=job.meta.get("message"),
        error=job.meta.get("error"),
        artifact_key=job.meta.get("artifact_key"),
        created_at=_datetime(job.created_at or job.enqueued_at),
        started_at=_datetime(job.started_at),
        ended_at=_datetime(job.ended_at),
    )


def _completed_artifact_response(
    *,
    job_id: str,
    year: int,
    round_number: int,
    manifest: dict[str, Any],
    path: Path,
) -> SessionImportJob:
    imported_at = datetime.fromisoformat(manifest["imported_at"])
    return SessionImportJob(
        id=job_id,
        session_key=manifest["session_key"],
        year=year,
        round_number=round_number,
        status="finished",
        progress=100,
        stage="complete",
        message="Session artifacts already exist",
        artifact_key=path.parent.name,
        created_at=imported_at,
        ended_at=imported_at,
    )


def enqueue_session_import(
    request: SessionImportRequest,
    *,
    settings: Settings,
    connection: Redis,
) -> SessionImportJob:
    """Idempotently enqueue or return one canonical race import."""
    key = session_key(request.year, request.round_number)
    job_id = _job_id(request.year, request.round_number)
    artifact_manifest = manifest_path(
        settings.import_dir,
        request.year,
        request.round_number,
    )
    artifact_exists = artifact_manifest.is_file()
    persistence_complete = artifact_exists and is_session_persisted(
        settings.database_url, key
    )
    if persistence_complete:
        return _completed_artifact_response(
            job_id=job_id,
            year=request.year,
            round_number=request.round_number,
            manifest=read_manifest(artifact_manifest),
            path=artifact_manifest,
        )

    queue = Queue(settings.import_queue_name, connection=connection)
    existing_job = queue.fetch_job(job_id)
    if existing_job is not None:
        status = existing_job.get_status(refresh=True)
        requires_database_backfill = (
            status == JobStatus.FINISHED and not persistence_complete
        )
        retryable_failure = request.retry_failed and status in {
            JobStatus.FAILED,
            JobStatus.STOPPED,
            JobStatus.CANCELED,
        }
        if requires_database_backfill or retryable_failure:
            existing_job.delete()
        else:
            return _job_response(existing_job)

    job = queue.enqueue_call(
        func=import_session_job,
        args=(request.year, request.round_number),
        timeout=settings.import_job_timeout_seconds,
        result_ttl=settings.import_result_ttl_seconds,
        failure_ttl=settings.import_result_ttl_seconds,
        job_id=job_id,
        description=f"Import {request.year} round {request.round_number} race",
        meta={
            "session_key": key,
            "year": request.year,
            "round_number": request.round_number,
            "progress": 0,
            "stage": "queued",
            "message": "Session import queued",
        },
    )
    return _job_response(job)


def get_session_import(job_id: str, *, connection: Redis) -> SessionImportJob:
    """Return current state for an RQ import job."""
    try:
        job = Job.fetch(job_id, connection=connection)
    except NoSuchJobError as error:
        raise ImportJobNotFoundError(job_id) from error
    return _job_response(job)


def _update_current_job(progress: int, stage: str, message: str) -> None:
    job = get_current_job()
    if job is None:
        return
    job.meta.update(
        {
            "progress": progress,
            "stage": stage,
            "message": message,
        }
    )
    job.save_meta()


def import_session_job(year: int, round_number: int) -> dict[str, Any]:
    """RQ task that imports artifacts and persists normalized session data."""
    settings = get_settings()

    def artifact_progress(progress: int, stage: str, message: str) -> None:
        _update_current_job(round(progress * 0.9), stage, message)

    try:
        manifest = import_race_session(
            year=year,
            round_number=round_number,
            cache_dir=settings.fastf1_cache_dir,
            import_dir=settings.import_dir,
            progress=artifact_progress,
        )
        _update_current_job(
            92,
            "persisting",
            "Loading normalized session data into PostgreSQL",
        )
        summary = persist_session_artifacts(
            manifest=manifest,
            import_dir=settings.import_dir,
            database_url=settings.database_url,
            job_id=_job_id(year, round_number),
        )
    except Exception as error:
        job = get_current_job()
        if job is not None:
            job.meta.update(
                {
                    "stage": "failed",
                    "message": "Session import failed",
                    "error": f"{type(error).__name__}: {error}"[:500],
                }
            )
            job.save_meta()
        raise

    job = get_current_job()
    if job is not None:
        job.meta.update(
            {
                "artifact_key": manifest["session_key"],
                "progress": 100,
                "stage": "complete",
                "message": "Session import and database persistence completed",
            }
        )
        job.save_meta()
    return {
        "artifact_key": manifest["session_key"],
        "telemetry_rows": manifest["telemetry_rows"],
        "session_id": summary.session_id,
        "lap_rows": summary.laps,
    }
