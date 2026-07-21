"""Normalized relational models for imported races and anomaly analyses."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from f1_telemetry.storage.base import Base


class TimestampMixin:
    """Creation timestamp shared by immutable import records."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Event(TimestampMixin, Base):
    """One championship event identified by season and round."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("year", "round_number", name="event_year_round"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    country: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(100))
    official_name: Mapped[str | None] = mapped_column(String(300))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    event_date: Mapped[date | None] = mapped_column(Date)
    event_format: Mapped[str | None] = mapped_column(String(50))
    f1_api_support: Mapped[bool | None] = mapped_column(Boolean)

    sessions: Mapped[list["RaceSession"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class RaceSession(TimestampMixin, Base):
    """A completed FastF1 session; the MVP stores race sessions only."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    session_code: Mapped[str] = mapped_column(String(8), nullable=False, default="R")
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    event: Mapped[Event] = relationship(back_populates="sessions")
    import_record: Mapped["ImportRecord | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    results: Mapped[list["Result"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    laps: Mapped[list["Lap"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    stints: Mapped[list["Stint"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    weather_samples: Mapped[list["WeatherSample"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    telemetry_files: Mapped[list["TelemetryFile"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    model_runs: Mapped[list["ModelRun"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Driver(TimestampMixin, Base):
    """Stable driver identity separated from session-specific results."""

    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    fastf1_driver_id: Mapped[str | None] = mapped_column(String(100), index=True)
    abbreviation: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    full_name: Mapped[str | None] = mapped_column(String(200))
    broadcast_name: Mapped[str | None] = mapped_column(String(200))
    country_code: Mapped[str | None] = mapped_column(String(8))
    headshot_url: Mapped[str | None] = mapped_column(Text)

    results: Mapped[list["Result"]] = relationship(back_populates="driver")
    laps: Mapped[list["Lap"]] = relationship(back_populates="driver")
    stints: Mapped[list["Stint"]] = relationship(back_populates="driver")
    telemetry_files: Mapped[list["TelemetryFile"]] = relationship(
        back_populates="driver"
    )


class ImportRecord(TimestampMixin, Base):
    """Traceability record joining an RQ job, manifest, and stored session."""

    __tablename__ = "imports"
    __table_args__ = (
        CheckConstraint("status IN ('completed', 'failed')", name="valid_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    session_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="FastF1")
    fastf1_version: Mapped[str] = mapped_column(String(30), nullable=False)
    manifest_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_path: Mapped[str] = mapped_column(Text, nullable=False)
    row_counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text)

    session: Mapped[RaceSession] = relationship(back_populates="import_record")


class Result(Base):
    """One driver's classification and team context for a race session."""

    __tablename__ = "results"
    __table_args__ = (
        UniqueConstraint("session_id", "driver_id", name="result_session_driver"),
        Index("ix_results_session_position", "session_id", "position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="RESTRICT"), nullable=False
    )
    driver_number: Mapped[str] = mapped_column(String(8), nullable=False)
    team_name: Mapped[str | None] = mapped_column(String(150))
    team_color: Mapped[str | None] = mapped_column(String(12))
    position: Mapped[int | None] = mapped_column(Integer)
    classified_position: Mapped[str | None] = mapped_column(String(20))
    grid_position: Mapped[int | None] = mapped_column(Integer)
    race_time_seconds: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(String(100))
    points: Mapped[float | None] = mapped_column(Float)
    q1_seconds: Mapped[float | None] = mapped_column(Float)
    q2_seconds: Mapped[float | None] = mapped_column(Float)
    q3_seconds: Mapped[float | None] = mapped_column(Float)

    session: Mapped[RaceSession] = relationship(back_populates="results")
    driver: Mapped[Driver] = relationship(back_populates="results")


class Lap(Base):
    """One normalized timing lap, used as the anomaly-scoring grain."""

    __tablename__ = "laps"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "driver_id", "lap_number", name="lap_session_driver_number"
        ),
        Index("ix_laps_session_driver", "session_id", "driver_id"),
        Index("ix_laps_session_number", "session_id", "lap_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="RESTRICT"), nullable=False
    )
    lap_number: Mapped[int] = mapped_column(Integer, nullable=False)
    stint_number: Mapped[int | None] = mapped_column(Integer)
    lap_time_seconds: Mapped[float | None] = mapped_column(Float)
    sector1_seconds: Mapped[float | None] = mapped_column(Float)
    sector2_seconds: Mapped[float | None] = mapped_column(Float)
    sector3_seconds: Mapped[float | None] = mapped_column(Float)
    sector1_session_seconds: Mapped[float | None] = mapped_column(Float)
    sector2_session_seconds: Mapped[float | None] = mapped_column(Float)
    sector3_session_seconds: Mapped[float | None] = mapped_column(Float)
    pit_out_seconds: Mapped[float | None] = mapped_column(Float)
    pit_in_seconds: Mapped[float | None] = mapped_column(Float)
    lap_start_seconds: Mapped[float | None] = mapped_column(Float)
    lap_start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    speed_i1: Mapped[float | None] = mapped_column(Float)
    speed_i2: Mapped[float | None] = mapped_column(Float)
    speed_fl: Mapped[float | None] = mapped_column(Float)
    speed_st: Mapped[float | None] = mapped_column(Float)
    is_personal_best: Mapped[bool | None] = mapped_column(Boolean)
    compound: Mapped[str | None] = mapped_column(String(30))
    tyre_life: Mapped[float | None] = mapped_column(Float)
    fresh_tyre: Mapped[bool | None] = mapped_column(Boolean)
    team_name: Mapped[str | None] = mapped_column(String(150))
    track_status: Mapped[str | None] = mapped_column(String(30))
    position: Mapped[int | None] = mapped_column(Integer)
    deleted: Mapped[bool | None] = mapped_column(Boolean)
    deleted_reason: Mapped[str | None] = mapped_column(Text)
    fastf1_generated: Mapped[bool | None] = mapped_column(Boolean)
    is_accurate: Mapped[bool | None] = mapped_column(Boolean)

    session: Mapped[RaceSession] = relationship(back_populates="laps")
    driver: Mapped[Driver] = relationship(back_populates="laps")
    anomaly_results: Mapped[list["AnomalyResult"]] = relationship(
        back_populates="lap", cascade="all, delete-orphan"
    )


class Stint(Base):
    """A continuous tire stint derived from one driver's laps."""

    __tablename__ = "stints"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "driver_id",
            "stint_number",
            name="stint_session_driver_number",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="RESTRICT"), nullable=False
    )
    stint_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_lap: Mapped[int] = mapped_column(Integer, nullable=False)
    end_lap: Mapped[int] = mapped_column(Integer, nullable=False)
    lap_count: Mapped[int] = mapped_column(Integer, nullable=False)
    compound: Mapped[str | None] = mapped_column(String(30))
    start_tyre_life: Mapped[float | None] = mapped_column(Float)
    end_tyre_life: Mapped[float | None] = mapped_column(Float)

    session: Mapped[RaceSession] = relationship(back_populates="stints")
    driver: Mapped[Driver] = relationship(back_populates="stints")


class WeatherSample(Base):
    """Session-relative weather observation from FastF1."""

    __tablename__ = "weather_samples"
    __table_args__ = (
        UniqueConstraint("session_id", "time_seconds", name="weather_session_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    air_temp: Mapped[float | None] = mapped_column(Float)
    humidity: Mapped[float | None] = mapped_column(Float)
    pressure: Mapped[float | None] = mapped_column(Float)
    rainfall: Mapped[bool | None] = mapped_column(Boolean)
    track_temp: Mapped[float | None] = mapped_column(Float)
    wind_direction: Mapped[int | None] = mapped_column(Integer)
    wind_speed: Mapped[float | None] = mapped_column(Float)

    session: Mapped[RaceSession] = relationship(back_populates="weather_samples")


class TelemetryFile(Base):
    """Portable reference to a session driver's compressed telemetry trace."""

    __tablename__ = "telemetry_files"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "driver_id", name="telemetry_file_session_driver"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="RESTRICT"), nullable=False
    )
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_format: Mapped[str] = mapped_column(String(20), nullable=False)
    compression: Mapped[str] = mapped_column(String(20), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    session: Mapped[RaceSession] = relationship(back_populates="telemetry_files")
    driver: Mapped[Driver] = relationship(back_populates="telemetry_files")


class ModelRun(TimestampMixin, Base):
    """A versioned feature/model execution for one session."""

    __tablename__ = "model_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="valid_status",
        ),
        Index("ix_model_runs_session_created", "session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(50), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    session: Mapped[RaceSession] = relationship(back_populates="model_runs")
    anomaly_results: Mapped[list["AnomalyResult"]] = relationship(
        back_populates="model_run", cascade="all, delete-orphan"
    )


class AnomalyResult(Base):
    """One lap's score, eligibility, severity, and explainable contributions."""

    __tablename__ = "anomaly_results"
    __table_args__ = (
        UniqueConstraint("model_run_id", "lap_id", name="anomaly_run_lap"),
        CheckConstraint(
            "severity IS NULL OR severity IN ('low', 'medium', 'high')",
            name="valid_severity",
        ),
        Index("ix_anomaly_results_run_score", "model_run_id", "score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_run_id: Mapped[int] = mapped_column(
        ForeignKey("model_runs.id", ondelete="CASCADE"), nullable=False
    )
    lap_id: Mapped[int] = mapped_column(
        ForeignKey("laps.id", ondelete="CASCADE"), nullable=False
    )
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(100))
    score: Mapped[float | None] = mapped_column(Float)
    severity: Mapped[str | None] = mapped_column(String(20))
    is_anomaly: Mapped[bool | None] = mapped_column(Boolean)
    contributions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)

    model_run: Mapped[ModelRun] = relationship(back_populates="anomaly_results")
    lap: Mapped[Lap] = relationship(back_populates="anomaly_results")
