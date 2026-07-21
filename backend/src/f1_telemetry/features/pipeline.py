"""Database-backed orchestration for versioned lap feature sets."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as parquet
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from f1_telemetry.features.calculator import (
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    PIPELINE_VERSION,
    FeatureConfig,
    calculate_lap_features,
    summarize_telemetry,
)
from f1_telemetry.storage.database import (
    create_database_engine,
    create_session_factory,
)
from f1_telemetry.storage.models import (
    Driver,
    FeatureRun,
    ImportRecord,
    Lap,
    LapFeature,
    RaceSession,
    TelemetryFile,
    WeatherSample,
)


@dataclass(frozen=True)
class FeaturePipelineSummary:
    """Stable result returned for a new or existing completed feature run."""

    feature_run_id: int
    session_key: str
    schema_version: str
    row_count: int
    eligible_count: int
    exclusion_counts: dict[str, int]


def _configuration_hash(config: FeatureConfig) -> str:
    payload = {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "feature_names": FEATURE_NAMES,
        "parameters": config.as_dict(),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def _load_laps(db: Session, session_id: int) -> pd.DataFrame:
    statement = (
        select(
            Lap.id.label("lap_id"),
            Lap.driver_id,
            Driver.abbreviation.label("driver"),
            Lap.lap_number,
            Lap.stint_number,
            Lap.lap_time_seconds,
            Lap.sector1_seconds,
            Lap.sector2_seconds,
            Lap.sector3_seconds,
            Lap.pit_out_seconds,
            Lap.pit_in_seconds,
            Lap.lap_start_seconds,
            Lap.compound,
            Lap.tyre_life,
            Lap.track_status,
            Lap.deleted,
            Lap.fastf1_generated,
            Lap.is_accurate,
            Lap.position,
        )
        .join(Driver, Driver.id == Lap.driver_id)
        .where(Lap.session_id == session_id)
        .order_by(Lap.lap_start_seconds, Lap.driver_id, Lap.lap_number)
    )
    return pd.DataFrame(db.execute(statement).mappings().all())


def _load_weather(db: Session, session_id: int) -> pd.DataFrame:
    statement = (
        select(
            WeatherSample.time_seconds,
            WeatherSample.air_temp,
            WeatherSample.humidity,
            WeatherSample.pressure,
            WeatherSample.rainfall,
            WeatherSample.track_temp,
            WeatherSample.wind_direction,
            WeatherSample.wind_speed,
        )
        .where(WeatherSample.session_id == session_id)
        .order_by(WeatherSample.time_seconds)
    )
    return pd.DataFrame(db.execute(statement).mappings().all())


def _load_telemetry_summaries(
    db: Session,
    *,
    session_id: int,
    artifact_dir: Path,
    config: FeatureConfig,
) -> pd.DataFrame:
    files = db.execute(
        select(TelemetryFile.driver_id, TelemetryFile.relative_path)
        .where(TelemetryFile.session_id == session_id)
        .order_by(TelemetryFile.driver_id)
    ).all()
    summaries: list[pd.DataFrame] = []
    columns = ["LapNumber", "Speed", "Throttle", "Brake", "nGear", "RPM"]
    for driver_id, relative_path in files:
        path = artifact_dir / str(relative_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        available_columns = set(parquet.ParquetFile(path).schema_arrow.names)
        readable_columns = [column for column in columns if column in available_columns]
        if "LapNumber" not in readable_columns:
            continue
        telemetry = pd.read_parquet(path, columns=readable_columns)
        for missing_column in set(columns).difference(readable_columns):
            telemetry[missing_column] = pd.NA
        summaries.append(
            summarize_telemetry(
                telemetry,
                driver_id=int(driver_id),
                full_throttle_threshold=config.full_throttle_threshold,
            )
        )
    if not summaries:
        return pd.DataFrame(
            columns=[
                "driver_id",
                "lap_number",
                "telemetry_sample_count",
                "speed_mean_kph",
                "speed_max_kph",
                "throttle_mean_pct",
                "full_throttle_fraction",
                "brake_fraction",
                "gear_change_count",
                "rpm_mean",
            ]
        )
    return pd.concat(summaries, ignore_index=True)


def _summary_from_run(
    db: Session,
    run: FeatureRun,
    session_key: str,
) -> FeaturePipelineSummary:
    reasons = db.execute(
        select(LapFeature.exclusion_reason)
        .where(
            LapFeature.feature_run_id == run.id,
            LapFeature.exclusion_reason.is_not(None),
        )
        .order_by(LapFeature.exclusion_reason)
    ).scalars()
    exclusion_counts: dict[str, int] = {}
    for reason in reasons:
        if reason is not None:
            exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
    return FeaturePipelineSummary(
        feature_run_id=run.id,
        session_key=session_key,
        schema_version=run.schema_version,
        row_count=run.row_count,
        eligible_count=run.eligible_count,
        exclusion_counts=exclusion_counts,
    )


def _feature_rows(frame: pd.DataFrame, run_id: int) -> list[LapFeature]:
    records: list[LapFeature] = []
    for row in frame.to_dict(orient="records"):
        exclusion = row.get("exclusion_reason")
        if exclusion is not None and pd.isna(exclusion):
            exclusion = None
        vector = row.get("feature_vector")
        if vector is not None and not isinstance(vector, list):
            vector = list(vector)
        records.append(
            LapFeature(
                feature_run_id=run_id,
                lap_id=int(row["lap_id"]),
                eligible=bool(row["eligible"]),
                exclusion_reason=str(exclusion) if exclusion is not None else None,
                comparison_group=str(row["comparison_group"]),
                comparison_sample_count=int(row["comparison_sample_count"]),
                is_wet=bool(row["is_wet"]),
                weather_changed_recently=bool(row["weather_changed_recently"]),
                feature_values=row["feature_values"],
                feature_vector=vector,
            )
        )
    return records


def build_session_features(
    *,
    database_url: str,
    import_dir: Path,
    session_key: str,
    config: FeatureConfig | None = None,
    force: bool = False,
) -> FeaturePipelineSummary:
    """Calculate and persist one idempotent feature set for a stored session."""
    active_config = config or FeatureConfig()
    config_hash = _configuration_hash(active_config)
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    run_id: int | None = None
    try:
        with factory.begin() as db:
            race_session = db.scalar(
                select(RaceSession).where(RaceSession.session_key == session_key)
            )
            if race_session is None:
                raise LookupError(f"session not found: {session_key}")
            source_import = db.scalar(
                select(ImportRecord).where(ImportRecord.session_id == race_session.id)
            )
            if source_import is None or source_import.status != "completed":
                raise LookupError(f"completed import not found: {session_key}")
            existing = db.scalar(
                select(FeatureRun).where(
                    FeatureRun.session_id == race_session.id,
                    FeatureRun.source_import_id == source_import.id,
                    FeatureRun.schema_version == FEATURE_SCHEMA_VERSION,
                    FeatureRun.config_hash == config_hash,
                )
            )
            if existing is not None and existing.status == "completed" and not force:
                return _summary_from_run(db, existing, session_key)
            if existing is None:
                existing = FeatureRun(
                    session_id=race_session.id,
                    source_import_id=source_import.id,
                    schema_version=FEATURE_SCHEMA_VERSION,
                    pipeline_version=PIPELINE_VERSION,
                    config_hash=config_hash,
                    parameters=active_config.as_dict(),
                    feature_names=list(FEATURE_NAMES),
                    status="running",
                    row_count=0,
                    eligible_count=0,
                    started_at=datetime.now(UTC),
                )
                db.add(existing)
                db.flush()
            else:
                existing.status = "running"
                existing.started_at = datetime.now(UTC)
                existing.completed_at = None
                existing.error = None
            run_id = existing.id
            session_id = race_session.id
            artifact_dir = import_dir / source_import.artifact_path

        with factory() as db:
            laps = _load_laps(db, session_id)
            weather = _load_weather(db, session_id)
            telemetry = _load_telemetry_summaries(
                db,
                session_id=session_id,
                artifact_dir=artifact_dir,
                config=active_config,
            )
        features = calculate_lap_features(laps, weather, telemetry, active_config)

        with factory.begin() as db:
            run = db.get(FeatureRun, run_id)
            if run is None:
                raise RuntimeError(f"feature run disappeared: {run_id}")
            db.execute(delete(LapFeature).where(LapFeature.feature_run_id == run_id))
            db.add_all(_feature_rows(features, run_id))
            run.status = "completed"
            run.row_count = len(features)
            run.eligible_count = int(features["eligible"].sum())
            run.completed_at = datetime.now(UTC)
            run.error = None
            db.flush()
            return _summary_from_run(db, run, session_key)
    except Exception as error:
        if run_id is not None:
            with factory.begin() as db:
                run = db.get(FeatureRun, run_id)
                if run is not None:
                    run.status = "failed"
                    run.error = f"{type(error).__name__}: {error}"[:1000]
                    run.completed_at = datetime.now(UTC)
        raise
    finally:
        engine.dispose()
