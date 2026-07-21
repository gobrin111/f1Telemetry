"""Command-line entry point for stored-session anomaly analysis."""

import argparse

from f1_telemetry.core.config import get_settings
from f1_telemetry.detection import SUPPORTED_DETECTORS
from f1_telemetry.detection.pipeline import build_session_analysis


def main() -> None:
    """Run one or both versioned anomaly detectors."""
    parser = argparse.ArgumentParser(description="Analyze stored lap features")
    parser.add_argument("session_key", help="Canonical key such as 2024-round-01-race")
    parser.add_argument(
        "--model",
        choices=(*SUPPORTED_DETECTORS, "all"),
        default="all",
        help="Detector to run (default: all)",
    )
    parser.add_argument("--feature-run-id", type=int)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild an existing analysis with the same configuration",
    )
    args = parser.parse_args()
    settings = get_settings()
    model_names = SUPPORTED_DETECTORS if args.model == "all" else (args.model,)
    for model_name in model_names:
        summary = build_session_analysis(
            database_url=settings.database_url,
            session_key=args.session_key,
            model_name=model_name,
            feature_run_id=args.feature_run_id,
            force=args.force,
        )
        print(
            f"model_run={summary.model_run_id} model={summary.model_name} "
            f"version={summary.model_version} feature_run={summary.feature_run_id} "
            f"rows={summary.row_count} scored={summary.scored_count} "
            f"severity={summary.severity_counts}"
        )
