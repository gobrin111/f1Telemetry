"""Known-value and persistence tests for lap anomaly detection."""

from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import func, select
from test_features import _seed_feature_session

from f1_telemetry.detection import DetectionConfig, score_feature_vectors
from f1_telemetry.detection.pipeline import build_session_analysis
from f1_telemetry.features import FeatureConfig
from f1_telemetry.features.pipeline import build_session_features
from f1_telemetry.storage.database import (
    create_database_engine,
    create_session_factory,
)
from f1_telemetry.storage.models import AnomalyResult, ModelRun


def _injected_vectors() -> tuple[np.ndarray, set[int]]:
    generator = np.random.default_rng(42)
    normal = generator.normal(0, 0.65, size=(300, 14))
    injected = generator.normal(0, 0.65, size=(10, 14))
    injected[:, [0, 1, 4, 6, 8]] += np.array([7, 6, -5, -6, 5])
    return np.vstack([normal, injected]), set(range(300, 310))


@pytest.mark.parametrize("model_name", ["robust", "isolation_forest"])
def test_injected_multivariate_anomalies_rank_at_the_top(model_name: str) -> None:
    vectors, injected_indexes = _injected_vectors()

    first = score_feature_vectors(vectors, model_name)
    repeated = score_feature_vectors(vectors, model_name)
    top_indexes = set(np.argsort(first.normalized_scores)[-10:])

    assert top_indexes == injected_indexes
    assert np.array_equal(first.normalized_scores, repeated.normalized_scores)
    assert np.all((first.normalized_scores >= 0) & (first.normalized_scores <= 1))
    assert first.contribution_strengths.shape == vectors.shape


def test_detection_config_rejects_overlapping_severity_bands() -> None:
    with pytest.raises(ValueError, match="severity thresholds"):
        DetectionConfig(low_threshold=0.9, medium_threshold=0.8)


def test_pipeline_scores_eligible_laps_and_propagates_exclusions(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'analysis.db'}"
    import_dir = tmp_path / "imports"
    _seed_feature_session(database_url, import_dir)
    feature_summary = build_session_features(
        database_url=database_url,
        import_dir=import_dir,
        session_key="2024-round-01-race",
        config=FeatureConfig(min_history_laps=3, history_window_laps=5),
    )

    robust = build_session_analysis(
        database_url=database_url,
        session_key="2024-round-01-race",
        feature_run_id=feature_summary.feature_run_id,
        model_name="robust",
    )
    repeated = build_session_analysis(
        database_url=database_url,
        session_key="2024-round-01-race",
        feature_run_id=feature_summary.feature_run_id,
        model_name="robust",
    )
    rebuilt = build_session_analysis(
        database_url=database_url,
        session_key="2024-round-01-race",
        feature_run_id=feature_summary.feature_run_id,
        model_name="robust",
        force=True,
    )
    isolation = build_session_analysis(
        database_url=database_url,
        session_key="2024-round-01-race",
        feature_run_id=feature_summary.feature_run_id,
        model_name="isolation_forest",
    )

    assert robust == repeated == rebuilt
    assert robust.row_count == 9
    assert robust.scored_count == 2
    assert isolation.scored_count == robust.scored_count

    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(ModelRun)) == 2
            assert db.scalar(select(func.count()).select_from(AnomalyResult)) == 18
            robust_results = db.scalars(
                select(AnomalyResult)
                .where(AnomalyResult.model_run_id == robust.model_run_id)
                .order_by(AnomalyResult.lap_id)
            ).all()
            scored = [result for result in robust_results if result.eligible]
            excluded = [result for result in robust_results if not result.eligible]
            assert len(scored) == 2
            assert all(result.score is not None for result in scored)
            assert all(result.exclusion_reason for result in excluded)
            assert all(result.score is None for result in excluded)
            assert all(len(result.contributions or []) == 5 for result in scored)
            contribution = scored[0].contributions[0]
            assert contribution["observed_value"] is not None
            assert contribution["baseline_value"] is not None
            assert contribution["method"] == "absolute_robust_z"
    finally:
        engine.dispose()
