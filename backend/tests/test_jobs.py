"""Redis Queue behavior around relational import persistence."""

from pathlib import Path

import fakeredis
from rq import Queue
from rq.job import Job, JobStatus

from f1_telemetry.core.config import Settings
from f1_telemetry.ingestion.jobs import (
    enqueue_session_import,
    import_session_job,
)
from f1_telemetry.ingestion.models import SessionImportRequest
from f1_telemetry.storage import Base
from f1_telemetry.storage.database import create_database_engine


def test_finished_artifact_without_database_record_is_requeued(
    tmp_path: Path,
) -> None:
    connection = fakeredis.FakeRedis()
    database_url = f"sqlite+pysqlite:///{tmp_path / 'jobs.db'}"
    engine = create_database_engine(database_url)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    settings = Settings(
        environment="test",
        import_dir=tmp_path / "imports",
        fastf1_cache_dir=tmp_path / "cache",
        database_url=database_url,
        _env_file=None,
    )
    manifest = settings.import_dir / "2024-round-01-race" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")

    job = Job.create(
        func=import_session_job,
        args=(2024, 1),
        id="import-2024-round-01-race",
        connection=connection,
    )
    job.meta.update(
        {
            "session_key": "2024-round-01-race",
            "year": 2024,
            "round_number": 1,
            "progress": 100,
            "stage": "complete",
        }
    )
    job.save()
    job.set_status(JobStatus.FINISHED)
    job.save()

    response = enqueue_session_import(
        SessionImportRequest(year=2024, round_number=1),
        settings=settings,
        connection=connection,
    )

    assert response.status == "queued"
    assert response.stage == "queued"
    assert Queue(settings.import_queue_name, connection=connection).count == 1
