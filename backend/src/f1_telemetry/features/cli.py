"""Command-line entry point for a stored session's feature pipeline."""

import argparse

from f1_telemetry.core.config import get_settings
from f1_telemetry.features.pipeline import build_session_features


def main() -> None:
    """Build or return one versioned lap feature set."""
    parser = argparse.ArgumentParser(description="Build lap features for a session")
    parser.add_argument("session_key", help="Canonical key such as 2024-round-01-race")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild an existing feature run with the same configuration",
    )
    args = parser.parse_args()
    settings = get_settings()
    summary = build_session_features(
        database_url=settings.database_url,
        import_dir=settings.import_dir,
        session_key=args.session_key,
        force=args.force,
    )
    print(
        f"feature_run={summary.feature_run_id} "
        f"rows={summary.row_count} eligible={summary.eligible_count} "
        f"excluded={summary.row_count - summary.eligible_count}"
    )
