"""Migration and transactional FastF1 artifact-persistence tests."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select

from f1_telemetry.storage import Base
from f1_telemetry.storage.database import (
    create_database_engine,
    create_session_factory,
)
from f1_telemetry.storage.models import (
    Driver,
    Event,
    ImportRecord,
    Lap,
    RaceSession,
    TelemetryFile,
)
from f1_telemetry.storage.persistence import (
    is_session_persisted,
    persist_session_artifacts,
    reconstruct_session,
)


def _write_artifact(import_dir: Path) -> dict[str, object]:
    key = "2024-round-01-race"
    artifact_dir = import_dir / key
    telemetry_dir = artifact_dir / "telemetry"
    telemetry_dir.mkdir(parents=True)

    tables = {
        "results": pd.DataFrame(
            {
                "DriverNumber": ["1", "2"],
                "Abbreviation": ["AAA", "BBB"],
                "DriverId": ["alpha", "bravo"],
                "FirstName": ["Alex", "Blair"],
                "LastName": ["Alpha", "Bravo"],
                "TeamName": ["Example One", "Example Two"],
                "Position": [1.0, 2.0],
                "ClassifiedPosition": ["1", "2"],
                "GridPosition": [2.0, 1.0],
                "Time": pd.to_timedelta([5400, 5401], unit="s"),
                "Status": ["Finished", "Finished"],
                "Points": [25.0, 18.0],
            }
        ),
        "laps": pd.DataFrame(
            {
                "Driver": ["AAA", "BBB"],
                "DriverNumber": ["1", "2"],
                "LapTime": pd.to_timedelta([90, 91], unit="s"),
                "LapNumber": [1.0, 1.0],
                "Stint": [1.0, 1.0],
                "Sector1Time": pd.to_timedelta([30, 30.5], unit="s"),
                "Sector2Time": pd.to_timedelta([30, 30.5], unit="s"),
                "Sector3Time": pd.to_timedelta([30, 30], unit="s"),
                "Compound": ["SOFT", "MEDIUM"],
                "TyreLife": [1.0, 1.0],
                "Deleted": [False, False],
                "IsAccurate": [True, True],
            }
        ),
        "stints": pd.DataFrame(
            {
                "Driver": ["AAA", "BBB"],
                "Stint": [1.0, 1.0],
                "StartLap": [1.0, 1.0],
                "EndLap": [1.0, 1.0],
                "LapCount": [1, 1],
                "Compound": ["SOFT", "MEDIUM"],
                "StartTyreLife": [1.0, 1.0],
                "EndTyreLife": [1.0, 1.0],
            }
        ),
        "weather": pd.DataFrame(
            {
                "Time": pd.to_timedelta([0], unit="s"),
                "AirTemp": [25.0],
                "Humidity": [55.0],
                "Rainfall": [False],
                "TrackTemp": [35.0],
            }
        ),
    }
    files: dict[str, dict[str, object]] = {}
    for name, frame in tables.items():
        path = artifact_dir / f"{name}.parquet"
        frame.to_parquet(path, index=False, compression="zstd")
        files[name] = {"path": path.name, "rows": len(frame)}

    telemetry_files: list[dict[str, object]] = []
    for driver in ("AAA", "BBB"):
        telemetry = pd.DataFrame(
            {
                "Driver": [driver, driver],
                "LapNumber": [1.0, 1.0],
                "Distance": [0.0, 100.0],
                "Speed": [200.0, 210.0],
            }
        )
        path = telemetry_dir / f"{driver}.parquet"
        telemetry.to_parquet(path, index=False, compression="zstd")
        telemetry_files.append(
            {
                "path": f"telemetry/{driver}.parquet",
                "rows": len(telemetry),
                "driver": driver,
            }
        )

    manifest: dict[str, object] = {
        "schema_version": 1,
        "session_key": key,
        "year": 2024,
        "round_number": 1,
        "session": "R",
        "session_name": "Race",
        "imported_at": datetime(2024, 3, 2, tzinfo=UTC).isoformat(),
        "fastf1_version": "3.8.3",
        "event": {
            "RoundNumber": 1,
            "Country": "Example",
            "Location": "Example City",
            "EventName": "Example Grand Prix",
            "EventDate": "2024-03-02T00:00:00",
            "EventFormat": "conventional",
            "F1ApiSupport": True,
        },
        "files": files,
        "telemetry_files": telemetry_files,
        "telemetry_rows": 4,
        "skipped_telemetry_laps": [],
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def _create_schema(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def test_migration_matches_current_models(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("F1_DATABASE_URL", database_url)
    backend_dir = Path(__file__).parents[1]
    config = Config(backend_dir / "alembic.ini")

    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    try:
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert set(Base.metadata.tables).issubset(table_names)
    assert "alembic_version" in table_names
    command.check(config)


def test_artifacts_are_persisted_idempotently_and_reconstructed(
    tmp_path: Path,
) -> None:
    import_dir = tmp_path / "imports"
    manifest = _write_artifact(import_dir)
    database_url = f"sqlite+pysqlite:///{tmp_path / 'storage.db'}"
    _create_schema(database_url)

    first = persist_session_artifacts(
        manifest=manifest,
        import_dir=import_dir,
        database_url=database_url,
        job_id="import-2024-round-01-race",
    )
    second = persist_session_artifacts(
        manifest=manifest,
        import_dir=import_dir,
        database_url=database_url,
        job_id="import-2024-round-01-race",
    )

    assert first == second
    assert first.results == 2
    assert first.laps == 2
    assert first.stints == 2
    assert first.weather_samples == 1
    assert first.telemetry_files == 2
    assert is_session_persisted(database_url, "2024-round-01-race") is True

    snapshot = reconstruct_session(
        database_url=database_url,
        import_dir=import_dir,
        session_key="2024-round-01-race",
    )
    assert snapshot.event_name == "Example Grand Prix"
    assert snapshot.counts == {
        "results": 2,
        "laps": 2,
        "stints": 2,
        "weather": 1,
        "telemetry_files": 2,
    }
    assert all(path.is_file() for path in snapshot.telemetry_paths)

    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory() as db:
            lap = db.scalar(select(Lap).where(Lap.lap_time_seconds == 90.0))
            telemetry_file = db.scalar(select(TelemetryFile))
            import_record = db.scalar(select(ImportRecord))
            assert lap is not None
            assert lap.driver.abbreviation == "AAA"
            assert telemetry_file is not None
            assert len(telemetry_file.sha256) == 64
            assert import_record is not None
            assert import_record.row_counts["telemetry"] == 4
            assert db.scalar(select(func.count()).select_from(RaceSession)) == 1
            assert db.scalar(select(func.count()).select_from(Driver)) == 2
    finally:
        engine.dispose()


def test_invalid_artifact_rolls_back_every_relational_row(tmp_path: Path) -> None:
    import_dir = tmp_path / "imports"
    manifest = _write_artifact(import_dir)
    telemetry_files = manifest["telemetry_files"]
    assert isinstance(telemetry_files, list)
    telemetry_files[0]["rows"] = 999
    database_url = f"sqlite+pysqlite:///{tmp_path / 'rollback.db'}"
    _create_schema(database_url)

    with pytest.raises(ValueError, match="telemetry row mismatch"):
        persist_session_artifacts(
            manifest=manifest,
            import_dir=import_dir,
            database_url=database_url,
            job_id="import-2024-round-01-race",
        )

    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(Event)) == 0
            assert db.scalar(select(func.count()).select_from(RaceSession)) == 0
            assert db.scalar(select(func.count()).select_from(ImportRecord)) == 0
    finally:
        engine.dispose()
