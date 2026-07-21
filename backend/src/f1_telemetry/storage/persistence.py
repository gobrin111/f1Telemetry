"""Transactional loading and reconstruction of FastF1 session artifacts."""

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as parquet
from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
    Result,
    Stint,
    TelemetryFile,
    WeatherSample,
)


@dataclass(frozen=True)
class PersistenceSummary:
    """Counts returned after an idempotent relational import."""

    session_id: int
    session_key: str
    results: int
    laps: int
    stints: int
    weather_samples: int
    telemetry_files: int


@dataclass(frozen=True)
class SessionStorageSnapshot:
    """Minimum data needed to prove a stored session can be reconstructed."""

    session_id: int
    session_key: str
    event_name: str
    year: int
    round_number: int
    counts: dict[str, int]
    telemetry_paths: tuple[Path, ...]


def _value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value.item() if hasattr(value, "item") else value


def _text(value: Any) -> str | None:
    cleaned = _value(value)
    return None if cleaned is None else str(cleaned)


def _first_text(*values: Any) -> str | None:
    for value in values:
        if text := _text(value):
            return text
    return None


def _float(value: Any) -> float | None:
    cleaned = _value(value)
    if cleaned is None:
        return None
    number = float(cleaned)
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _float(value)
    return None if number is None else int(number)


def _bool(value: Any) -> bool | None:
    cleaned = _value(value)
    return None if cleaned is None else bool(cleaned)


def _seconds(value: Any) -> float | None:
    cleaned = _value(value)
    if cleaned is None:
        return None
    if isinstance(cleaned, pd.Timedelta | timedelta):
        return cleaned.total_seconds()
    return _float(cleaned)


def _datetime(value: Any) -> datetime | None:
    cleaned = _value(value)
    if cleaned is None:
        return None
    if isinstance(cleaned, str):
        parsed = datetime.fromisoformat(cleaned)
    elif isinstance(cleaned, pd.Timestamp):
        parsed = cleaned.to_pydatetime()
    elif isinstance(cleaned, datetime):
        parsed = cleaned
    else:
        raise TypeError(f"unsupported datetime value: {type(cleaned).__name__}")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _date(value: Any) -> date | None:
    cleaned = _value(value)
    if cleaned is None:
        return None
    if isinstance(cleaned, str):
        return date.fromisoformat(cleaned[:10])
    if isinstance(cleaned, pd.Timestamp | datetime):
        return cleaned.date()
    if isinstance(cleaned, date):
        return cleaned
    raise TypeError(f"unsupported date value: {type(cleaned).__name__}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        while chunk := artifact.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_table(
    artifact_dir: Path, manifest: dict[str, Any], name: str
) -> pd.DataFrame:
    relative_path = manifest["files"][name]["path"]
    return pd.read_parquet(artifact_dir / relative_path)


def _driver_key(row: dict[str, Any], year: int) -> str:
    fastf1_driver_id = _text(row.get("DriverId"))
    if fastf1_driver_id:
        return f"fastf1:{fastf1_driver_id}"
    driver_number = _text(row.get("DriverNumber"))
    if driver_number:
        return f"season-number:{year}:{driver_number}"
    abbreviation = _first_text(row.get("Abbreviation"), row.get("Driver"))
    if abbreviation:
        return f"season-code:{year}:{abbreviation}"
    raise ValueError("driver row has no stable identifier")


def _upsert_driver(
    db: Session,
    row: dict[str, Any],
    year: int,
) -> Driver:
    key = _driver_key(row, year)
    driver = db.scalar(select(Driver).where(Driver.driver_key == key))
    abbreviation = _first_text(row.get("Abbreviation"), row.get("Driver"))
    if driver is None:
        if abbreviation is None:
            raise ValueError(f"driver {key} has no abbreviation")
        driver = Driver(driver_key=key, abbreviation=abbreviation)
        db.add(driver)

    updates = {
        "fastf1_driver_id": _text(row.get("DriverId")),
        "abbreviation": abbreviation,
        "first_name": _text(row.get("FirstName")),
        "last_name": _text(row.get("LastName")),
        "full_name": _text(row.get("FullName")),
        "broadcast_name": _text(row.get("BroadcastName")),
        "country_code": _text(row.get("CountryCode")),
        "headshot_url": _text(row.get("HeadshotUrl")),
    }
    for field, value in updates.items():
        if value is not None:
            setattr(driver, field, value)
    db.flush()
    return driver


def _event_from_manifest(db: Session, manifest: dict[str, Any]) -> Event:
    year = int(manifest["year"])
    round_number = int(manifest["round_number"])
    event = db.scalar(
        select(Event).where(
            Event.year == year,
            Event.round_number == round_number,
        )
    )
    metadata = manifest.get("event", {})
    values = {
        "country": _text(metadata.get("Country")),
        "location": _text(metadata.get("Location")),
        "official_name": _text(metadata.get("OfficialEventName")),
        "name": _text(metadata.get("EventName")) or f"Round {round_number}",
        "event_date": _date(metadata.get("EventDate")),
        "event_format": _text(metadata.get("EventFormat")),
        "f1_api_support": _bool(metadata.get("F1ApiSupport")),
    }
    if event is None:
        event = Event(year=year, round_number=round_number, **values)
        db.add(event)
    else:
        for field, value in values.items():
            if value is not None:
                setattr(event, field, value)
    db.flush()
    return event


def _driver_for_row(
    db: Session,
    row: dict[str, Any],
    year: int,
    by_number: dict[str, Driver],
    by_abbreviation: dict[str, Driver],
) -> Driver:
    number = _text(row.get("DriverNumber"))
    abbreviation = _first_text(row.get("Driver"), row.get("Abbreviation"))
    driver = by_number.get(number or "") or by_abbreviation.get(abbreviation or "")
    if driver is None:
        driver = _upsert_driver(
            db,
            {
                "DriverNumber": number,
                "Abbreviation": abbreviation,
                "Driver": abbreviation,
            },
            year,
        )
    if number:
        by_number[number] = driver
    if abbreviation:
        by_abbreviation[abbreviation] = driver
    return driver


def _load_results(
    db: Session,
    race_session: RaceSession,
    frame: pd.DataFrame,
    year: int,
) -> tuple[dict[str, Driver], dict[str, Driver]]:
    by_number: dict[str, Driver] = {}
    by_abbreviation: dict[str, Driver] = {}
    for row in frame.to_dict(orient="records"):
        driver = _upsert_driver(db, row, year)
        number = _text(row.get("DriverNumber"))
        abbreviation = _text(row.get("Abbreviation"))
        if number is None:
            raise ValueError(f"driver {driver.abbreviation} has no number")
        by_number[number] = driver
        if abbreviation:
            by_abbreviation[abbreviation] = driver
        db.add(
            Result(
                session=race_session,
                driver=driver,
                driver_number=number,
                team_name=_text(row.get("TeamName")),
                team_color=_text(row.get("TeamColor")),
                position=_int(row.get("Position")),
                classified_position=_text(row.get("ClassifiedPosition")),
                grid_position=_int(row.get("GridPosition")),
                race_time_seconds=_seconds(row.get("Time")),
                status=_text(row.get("Status")),
                points=_float(row.get("Points")),
                q1_seconds=_seconds(row.get("Q1")),
                q2_seconds=_seconds(row.get("Q2")),
                q3_seconds=_seconds(row.get("Q3")),
            )
        )
    return by_number, by_abbreviation


def _load_laps(
    db: Session,
    race_session: RaceSession,
    frame: pd.DataFrame,
    year: int,
    by_number: dict[str, Driver],
    by_abbreviation: dict[str, Driver],
) -> None:
    for row in frame.to_dict(orient="records"):
        lap_number = _int(row.get("LapNumber"))
        if lap_number is None:
            continue
        driver = _driver_for_row(db, row, year, by_number, by_abbreviation)
        db.add(
            Lap(
                session=race_session,
                driver=driver,
                lap_number=lap_number,
                stint_number=_int(row.get("Stint")),
                lap_time_seconds=_seconds(row.get("LapTime")),
                sector1_seconds=_seconds(row.get("Sector1Time")),
                sector2_seconds=_seconds(row.get("Sector2Time")),
                sector3_seconds=_seconds(row.get("Sector3Time")),
                sector1_session_seconds=_seconds(row.get("Sector1SessionTime")),
                sector2_session_seconds=_seconds(row.get("Sector2SessionTime")),
                sector3_session_seconds=_seconds(row.get("Sector3SessionTime")),
                pit_out_seconds=_seconds(row.get("PitOutTime")),
                pit_in_seconds=_seconds(row.get("PitInTime")),
                lap_start_seconds=_seconds(row.get("LapStartTime")),
                lap_start_date=_datetime(row.get("LapStartDate")),
                speed_i1=_float(row.get("SpeedI1")),
                speed_i2=_float(row.get("SpeedI2")),
                speed_fl=_float(row.get("SpeedFL")),
                speed_st=_float(row.get("SpeedST")),
                is_personal_best=_bool(row.get("IsPersonalBest")),
                compound=_text(row.get("Compound")),
                tyre_life=_float(row.get("TyreLife")),
                fresh_tyre=_bool(row.get("FreshTyre")),
                team_name=_text(row.get("Team")),
                track_status=_text(row.get("TrackStatus")),
                position=_int(row.get("Position")),
                deleted=_bool(row.get("Deleted")),
                deleted_reason=_text(row.get("DeletedReason")),
                fastf1_generated=_bool(row.get("FastF1Generated")),
                is_accurate=_bool(row.get("IsAccurate")),
            )
        )


def _load_stints(
    db: Session,
    race_session: RaceSession,
    frame: pd.DataFrame,
    year: int,
    by_number: dict[str, Driver],
    by_abbreviation: dict[str, Driver],
) -> None:
    for row in frame.to_dict(orient="records"):
        driver = _driver_for_row(db, row, year, by_number, by_abbreviation)
        values = {
            "stint_number": _int(row.get("Stint")),
            "start_lap": _int(row.get("StartLap")),
            "end_lap": _int(row.get("EndLap")),
            "lap_count": _int(row.get("LapCount")),
        }
        if any(value is None for value in values.values()):
            continue
        db.add(
            Stint(
                session=race_session,
                driver=driver,
                **values,
                compound=_text(row.get("Compound")),
                start_tyre_life=_float(row.get("StartTyreLife")),
                end_tyre_life=_float(row.get("EndTyreLife")),
            )
        )


def _load_weather(
    db: Session,
    race_session: RaceSession,
    frame: pd.DataFrame,
) -> None:
    for row in frame.to_dict(orient="records"):
        time_seconds = _seconds(row.get("Time"))
        if time_seconds is None:
            continue
        db.add(
            WeatherSample(
                session=race_session,
                time_seconds=time_seconds,
                air_temp=_float(row.get("AirTemp")),
                humidity=_float(row.get("Humidity")),
                pressure=_float(row.get("Pressure")),
                rainfall=_bool(row.get("Rainfall")),
                track_temp=_float(row.get("TrackTemp")),
                wind_direction=_int(row.get("WindDirection")),
                wind_speed=_float(row.get("WindSpeed")),
            )
        )


def _load_telemetry_references(
    db: Session,
    race_session: RaceSession,
    manifest: dict[str, Any],
    artifact_dir: Path,
    year: int,
    by_number: dict[str, Driver],
    by_abbreviation: dict[str, Driver],
) -> None:
    for item in manifest.get("telemetry_files", []):
        relative_path = Path(item["path"])
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"unsafe telemetry path: {relative_path}")
        artifact_path = artifact_dir / relative_path
        if not artifact_path.is_file():
            raise FileNotFoundError(artifact_path)
        driver = _driver_for_row(
            db,
            {"Driver": item.get("driver")},
            year,
            by_number,
            by_abbreviation,
        )
        parquet_rows = parquet.ParquetFile(artifact_path).metadata.num_rows
        expected_rows = int(item["rows"])
        if parquet_rows != expected_rows:
            raise ValueError(
                f"telemetry row mismatch for {relative_path}: "
                f"expected {expected_rows}, found {parquet_rows}"
            )
        db.add(
            TelemetryFile(
                session=race_session,
                driver=driver,
                relative_path=relative_path.as_posix(),
                file_format="parquet",
                compression="zstd",
                row_count=expected_rows,
                byte_size=artifact_path.stat().st_size,
                sha256=_sha256(artifact_path),
            )
        )


def _summary(db: Session, race_session: RaceSession) -> PersistenceSummary:
    def count(model: type[Any]) -> int:
        return int(
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.session_id == race_session.id)
            )
            or 0
        )

    return PersistenceSummary(
        session_id=race_session.id,
        session_key=race_session.session_key,
        results=count(Result),
        laps=count(Lap),
        stints=count(Stint),
        weather_samples=count(WeatherSample),
        telemetry_files=count(TelemetryFile),
    )


def persist_session_artifacts(
    *,
    manifest: dict[str, Any],
    import_dir: Path,
    database_url: str,
    job_id: str,
) -> PersistenceSummary:
    """Idempotently load a complete artifact into one database transaction."""
    artifact_dir = import_dir / manifest["session_key"]
    if not (artifact_dir / "manifest.json").is_file():
        raise FileNotFoundError(artifact_dir / "manifest.json")

    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory.begin() as db:
            existing = db.scalar(
                select(ImportRecord).where(
                    ImportRecord.session_key == manifest["session_key"],
                    ImportRecord.status == "completed",
                )
            )
            if existing is not None:
                return _summary(db, existing.session)

            event = _event_from_manifest(db, manifest)
            race_session = RaceSession(
                event=event,
                session_key=manifest["session_key"],
                session_code=manifest["session"],
                name=manifest["session_name"],
            )
            db.add(race_session)
            db.flush()

            results = _read_table(artifact_dir, manifest, "results")
            laps = _read_table(artifact_dir, manifest, "laps")
            stints = _read_table(artifact_dir, manifest, "stints")
            weather = _read_table(artifact_dir, manifest, "weather")
            by_number, by_abbreviation = _load_results(
                db, race_session, results, int(manifest["year"])
            )
            _load_laps(
                db,
                race_session,
                laps,
                int(manifest["year"]),
                by_number,
                by_abbreviation,
            )
            _load_stints(
                db,
                race_session,
                stints,
                int(manifest["year"]),
                by_number,
                by_abbreviation,
            )
            _load_weather(db, race_session, weather)
            _load_telemetry_references(
                db,
                race_session,
                manifest,
                artifact_dir,
                int(manifest["year"]),
                by_number,
                by_abbreviation,
            )

            row_counts = {
                name: int(details["rows"])
                for name, details in manifest["files"].items()
            }
            row_counts["telemetry"] = int(manifest["telemetry_rows"])
            imported_at = _datetime(manifest["imported_at"])
            if imported_at is None:
                raise ValueError("manifest imported_at is required")
            db.add(
                ImportRecord(
                    job_id=job_id,
                    session=race_session,
                    session_key=manifest["session_key"],
                    status="completed",
                    source="FastF1",
                    fastf1_version=manifest["fastf1_version"],
                    manifest_schema_version=int(manifest["schema_version"]),
                    artifact_path=manifest["session_key"],
                    manifest_path=f"{manifest['session_key']}/manifest.json",
                    row_counts=row_counts,
                    source_imported_at=imported_at,
                    completed_at=datetime.now(UTC),
                )
            )
            db.flush()
            return _summary(db, race_session)
    finally:
        engine.dispose()


def is_session_persisted(database_url: str, session_key: str) -> bool:
    """Return whether a completed relational import exists for a session."""
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory() as db:
            return (
                db.scalar(
                    select(ImportRecord.id).where(
                        ImportRecord.session_key == session_key,
                        ImportRecord.status == "completed",
                    )
                )
                is not None
            )
    finally:
        engine.dispose()


def reconstruct_session(
    *,
    database_url: str,
    import_dir: Path,
    session_key: str,
) -> SessionStorageSnapshot:
    """Reconstruct session identity, row counts, and telemetry locations."""
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory() as db:
            race_session = db.scalar(
                select(RaceSession).where(RaceSession.session_key == session_key)
            )
            if race_session is None or race_session.import_record is None:
                raise LookupError(session_key)
            summary = _summary(db, race_session)
            telemetry_files = db.scalars(
                select(TelemetryFile)
                .where(TelemetryFile.session_id == race_session.id)
                .order_by(TelemetryFile.relative_path)
            ).all()
            paths = tuple(
                import_dir
                / race_session.import_record.artifact_path
                / item.relative_path
                for item in telemetry_files
            )
            if any(not path.is_file() for path in paths):
                raise FileNotFoundError("one or more telemetry artifacts are missing")
            return SessionStorageSnapshot(
                session_id=race_session.id,
                session_key=race_session.session_key,
                event_name=race_session.event.name,
                year=race_session.event.year,
                round_number=race_session.event.round_number,
                counts={
                    "results": summary.results,
                    "laps": summary.laps,
                    "stints": summary.stints,
                    "weather": summary.weather_samples,
                    "telemetry_files": summary.telemetry_files,
                },
                telemetry_paths=paths,
            )
    finally:
        engine.dispose()
