"""Add reproducible anomaly-run metadata.

Revision ID: 20260721_03
Revises: 20260721_02
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_03"
down_revision: str | Sequence[str] | None = "20260721_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add model configuration identity, metrics, and scoring counts."""
    with op.batch_alter_table("model_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "config_hash",
                sa.String(length=64),
                server_default="legacy",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("metrics", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("row_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("scored_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.create_unique_constraint(
            "model_run_feature_config",
            ["feature_run_id", "model_name", "model_version", "config_hash"],
        )
        batch_op.alter_column("config_hash", server_default=None)
        batch_op.alter_column("row_count", server_default=None)
        batch_op.alter_column("scored_count", server_default=None)


def downgrade() -> None:
    """Remove anomaly-run reproducibility metadata."""
    with op.batch_alter_table("model_runs") as batch_op:
        batch_op.drop_constraint("model_run_feature_config", type_="unique")
        batch_op.drop_column("scored_count")
        batch_op.drop_column("row_count")
        batch_op.drop_column("metrics")
        batch_op.drop_column("config_hash")
