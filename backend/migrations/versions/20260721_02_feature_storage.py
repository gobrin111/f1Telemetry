"""Create versioned lap feature storage.

Revision ID: 20260721_02
Revises: 20260721_01
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_02"
down_revision: str | Sequence[str] | None = "20260721_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create feature runs and per-lap feature rows."""
    op.create_table(
        "feature_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("source_import_id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column("pipeline_version", sa.String(length=30), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("feature_names", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("eligible_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_feature_runs_valid_status",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_feature_runs_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_import_id"],
            ["imports.id"],
            name="fk_feature_runs_source_import_id_imports",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feature_runs"),
        sa.UniqueConstraint(
            "session_id",
            "source_import_id",
            "schema_version",
            "config_hash",
            name="feature_run_source_config",
        ),
    )
    op.create_index(
        "ix_feature_runs_session_created",
        "feature_runs",
        ["session_id", "created_at"],
    )

    op.create_table(
        "lap_features",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("feature_run_id", sa.Integer(), nullable=False),
        sa.Column("lap_id", sa.Integer(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.String(length=100), nullable=True),
        sa.Column("comparison_group", sa.String(length=200), nullable=False),
        sa.Column("comparison_sample_count", sa.Integer(), nullable=False),
        sa.Column("is_wet", sa.Boolean(), nullable=False),
        sa.Column("weather_changed_recently", sa.Boolean(), nullable=False),
        sa.Column("feature_values", sa.JSON(), nullable=False),
        sa.Column("feature_vector", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["feature_run_id"],
            ["feature_runs.id"],
            name="fk_lap_features_feature_run_id_feature_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lap_id"],
            ["laps.id"],
            name="fk_lap_features_lap_id_laps",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lap_features"),
        sa.UniqueConstraint("feature_run_id", "lap_id", name="lap_feature_run_lap"),
    )
    op.create_index(
        "ix_lap_features_run_eligible",
        "lap_features",
        ["feature_run_id", "eligible"],
    )
    op.create_index(
        "ix_lap_features_run_exclusion",
        "lap_features",
        ["feature_run_id", "exclusion_reason"],
    )

    with op.batch_alter_table("model_runs") as batch_op:
        batch_op.add_column(sa.Column("feature_run_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            "ix_model_runs_feature_run_id", ["feature_run_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_model_runs_feature_run_id_feature_runs",
            "feature_runs",
            ["feature_run_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    """Remove feature storage and exact model-run feature references."""
    with op.batch_alter_table("model_runs") as batch_op:
        batch_op.drop_constraint(
            "fk_model_runs_feature_run_id_feature_runs", type_="foreignkey"
        )
        batch_op.drop_index("ix_model_runs_feature_run_id")
        batch_op.drop_column("feature_run_id")

    op.drop_index("ix_lap_features_run_exclusion", table_name="lap_features")
    op.drop_index("ix_lap_features_run_eligible", table_name="lap_features")
    op.drop_table("lap_features")
    op.drop_index("ix_feature_runs_session_created", table_name="feature_runs")
    op.drop_table("feature_runs")
