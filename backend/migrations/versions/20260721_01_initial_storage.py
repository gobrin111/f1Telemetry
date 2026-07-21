"""Create normalized import and anomaly storage.

Revision ID: 20260721_01
Revises:
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_01"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the Phase 5 storage schema."""
    op.create_table(
        "drivers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("driver_key", sa.String(length=120), nullable=False),
        sa.Column("fastf1_driver_id", sa.String(length=100), nullable=True),
        sa.Column("abbreviation", sa.String(length=8), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=True),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("broadcast_name", sa.String(length=200), nullable=True),
        sa.Column("country_code", sa.String(length=8), nullable=True),
        sa.Column("headshot_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_drivers"),
        sa.UniqueConstraint("driver_key", name="uq_drivers_driver_key"),
    )
    op.create_index("ix_drivers_abbreviation", "drivers", ["abbreviation"])
    op.create_index("ix_drivers_fastf1_driver_id", "drivers", ["fastf1_driver_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("location", sa.String(length=100), nullable=True),
        sa.Column("official_name", sa.String(length=300), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("event_format", sa.String(length=50), nullable=True),
        sa.Column("f1_api_support", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
        sa.UniqueConstraint("year", "round_number", name="event_year_round"),
    )
    op.create_index("ix_events_year", "events", ["year"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("session_key", sa.String(length=80), nullable=False),
        sa.Column("session_code", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name="fk_sessions_event_id_events",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.UniqueConstraint("session_key", name="uq_sessions_session_key"),
    )
    op.create_index("ix_sessions_event_id", "sessions", ["event_id"])

    op.create_table(
        "imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=120), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("session_key", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("fastf1_version", sa.String(length=30), nullable=False),
        sa.Column("manifest_schema_version", sa.Integer(), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("manifest_path", sa.Text(), nullable=False),
        sa.Column("row_counts", sa.JSON(), nullable=False),
        sa.Column("source_imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'failed')", name="ck_imports_valid_status"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_imports_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_imports"),
        sa.UniqueConstraint("job_id", name="uq_imports_job_id"),
        sa.UniqueConstraint("session_id", name="uq_imports_session_id"),
        sa.UniqueConstraint("session_key", name="uq_imports_session_key"),
    )

    op.create_table(
        "laps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("lap_number", sa.Integer(), nullable=False),
        sa.Column("stint_number", sa.Integer(), nullable=True),
        sa.Column("lap_time_seconds", sa.Float(), nullable=True),
        sa.Column("sector1_seconds", sa.Float(), nullable=True),
        sa.Column("sector2_seconds", sa.Float(), nullable=True),
        sa.Column("sector3_seconds", sa.Float(), nullable=True),
        sa.Column("sector1_session_seconds", sa.Float(), nullable=True),
        sa.Column("sector2_session_seconds", sa.Float(), nullable=True),
        sa.Column("sector3_session_seconds", sa.Float(), nullable=True),
        sa.Column("pit_out_seconds", sa.Float(), nullable=True),
        sa.Column("pit_in_seconds", sa.Float(), nullable=True),
        sa.Column("lap_start_seconds", sa.Float(), nullable=True),
        sa.Column("lap_start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("speed_i1", sa.Float(), nullable=True),
        sa.Column("speed_i2", sa.Float(), nullable=True),
        sa.Column("speed_fl", sa.Float(), nullable=True),
        sa.Column("speed_st", sa.Float(), nullable=True),
        sa.Column("is_personal_best", sa.Boolean(), nullable=True),
        sa.Column("compound", sa.String(length=30), nullable=True),
        sa.Column("tyre_life", sa.Float(), nullable=True),
        sa.Column("fresh_tyre", sa.Boolean(), nullable=True),
        sa.Column("team_name", sa.String(length=150), nullable=True),
        sa.Column("track_status", sa.String(length=30), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("deleted", sa.Boolean(), nullable=True),
        sa.Column("deleted_reason", sa.Text(), nullable=True),
        sa.Column("fastf1_generated", sa.Boolean(), nullable=True),
        sa.Column("is_accurate", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["drivers.id"],
            name="fk_laps_driver_id_drivers",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_laps_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_laps"),
        sa.UniqueConstraint(
            "session_id", "driver_id", "lap_number", name="lap_session_driver_number"
        ),
    )
    op.create_index("ix_laps_session_driver", "laps", ["session_id", "driver_id"])
    op.create_index("ix_laps_session_number", "laps", ["session_id", "lap_number"])

    op.create_table(
        "model_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=120), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column("feature_schema_version", sa.String(length=50), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_model_runs_valid_status",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_model_runs_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_runs"),
        sa.UniqueConstraint("job_id", name="uq_model_runs_job_id"),
    )
    op.create_index(
        "ix_model_runs_session_created", "model_runs", ["session_id", "created_at"]
    )

    op.create_table(
        "results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("driver_number", sa.String(length=8), nullable=False),
        sa.Column("team_name", sa.String(length=150), nullable=True),
        sa.Column("team_color", sa.String(length=12), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("classified_position", sa.String(length=20), nullable=True),
        sa.Column("grid_position", sa.Integer(), nullable=True),
        sa.Column("race_time_seconds", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=100), nullable=True),
        sa.Column("points", sa.Float(), nullable=True),
        sa.Column("q1_seconds", sa.Float(), nullable=True),
        sa.Column("q2_seconds", sa.Float(), nullable=True),
        sa.Column("q3_seconds", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["drivers.id"],
            name="fk_results_driver_id_drivers",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_results_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_results"),
        sa.UniqueConstraint("session_id", "driver_id", name="result_session_driver"),
    )
    op.create_index(
        "ix_results_session_position", "results", ["session_id", "position"]
    )

    op.create_table(
        "stints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("stint_number", sa.Integer(), nullable=False),
        sa.Column("start_lap", sa.Integer(), nullable=False),
        sa.Column("end_lap", sa.Integer(), nullable=False),
        sa.Column("lap_count", sa.Integer(), nullable=False),
        sa.Column("compound", sa.String(length=30), nullable=True),
        sa.Column("start_tyre_life", sa.Float(), nullable=True),
        sa.Column("end_tyre_life", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["drivers.id"],
            name="fk_stints_driver_id_drivers",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_stints_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stints"),
        sa.UniqueConstraint(
            "session_id",
            "driver_id",
            "stint_number",
            name="stint_session_driver_number",
        ),
    )
    op.create_index("ix_stints_session_id", "stints", ["session_id"])

    op.create_table(
        "telemetry_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("file_format", sa.String(length=20), nullable=False),
        sa.Column("compression", sa.String(length=20), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["drivers.id"],
            name="fk_telemetry_files_driver_id_drivers",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_telemetry_files_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_telemetry_files"),
        sa.UniqueConstraint(
            "session_id", "driver_id", name="telemetry_file_session_driver"
        ),
    )
    op.create_index("ix_telemetry_files_session_id", "telemetry_files", ["session_id"])

    op.create_table(
        "weather_samples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("time_seconds", sa.Float(), nullable=False),
        sa.Column("air_temp", sa.Float(), nullable=True),
        sa.Column("humidity", sa.Float(), nullable=True),
        sa.Column("pressure", sa.Float(), nullable=True),
        sa.Column("rainfall", sa.Boolean(), nullable=True),
        sa.Column("track_temp", sa.Float(), nullable=True),
        sa.Column("wind_direction", sa.Integer(), nullable=True),
        sa.Column("wind_speed", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_weather_samples_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_weather_samples"),
        sa.UniqueConstraint("session_id", "time_seconds", name="weather_session_time"),
    )
    op.create_index("ix_weather_samples_session_id", "weather_samples", ["session_id"])

    op.create_table(
        "anomaly_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_run_id", sa.Integer(), nullable=False),
        sa.Column("lap_id", sa.Integer(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.String(length=100), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.Column("is_anomaly", sa.Boolean(), nullable=True),
        sa.Column("contributions", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "severity IS NULL OR severity IN ('low', 'medium', 'high')",
            name="ck_anomaly_results_valid_severity",
        ),
        sa.ForeignKeyConstraint(
            ["lap_id"],
            ["laps.id"],
            name="fk_anomaly_results_lap_id_laps",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_run_id"],
            ["model_runs.id"],
            name="fk_anomaly_results_model_run_id_model_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_anomaly_results"),
        sa.UniqueConstraint("model_run_id", "lap_id", name="anomaly_run_lap"),
    )
    op.create_index(
        "ix_anomaly_results_run_score", "anomaly_results", ["model_run_id", "score"]
    )


def downgrade() -> None:
    """Remove the Phase 5 storage schema."""
    op.drop_index("ix_anomaly_results_run_score", table_name="anomaly_results")
    op.drop_table("anomaly_results")
    op.drop_index("ix_weather_samples_session_id", table_name="weather_samples")
    op.drop_table("weather_samples")
    op.drop_index("ix_telemetry_files_session_id", table_name="telemetry_files")
    op.drop_table("telemetry_files")
    op.drop_index("ix_stints_session_id", table_name="stints")
    op.drop_table("stints")
    op.drop_index("ix_results_session_position", table_name="results")
    op.drop_table("results")
    op.drop_index("ix_model_runs_session_created", table_name="model_runs")
    op.drop_table("model_runs")
    op.drop_index("ix_laps_session_number", table_name="laps")
    op.drop_index("ix_laps_session_driver", table_name="laps")
    op.drop_table("laps")
    op.drop_table("imports")
    op.drop_index("ix_sessions_event_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_events_year", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_drivers_fastf1_driver_id", table_name="drivers")
    op.drop_index("ix_drivers_abbreviation", table_name="drivers")
    op.drop_table("drivers")
