"""Pure, deterministic anomaly scoring for lap feature vectors."""

from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import IsolationForest

SUPPORTED_DETECTORS = ("robust", "isolation_forest")
DETECTOR_VERSIONS = {
    "robust": "1.0.0",
    "isolation_forest": "1.0.0",
}


@dataclass(frozen=True)
class DetectionConfig:
    """Parameters shared by reproducible detection runs."""

    low_threshold: float = 0.90
    medium_threshold: float = 0.97
    high_threshold: float = 0.995
    top_contributions: int = 5
    robust_top_features: int = 3
    isolation_estimators: int = 300
    isolation_max_samples: str | int = "auto"
    isolation_contamination: str | float = "auto"
    random_state: int = 42

    def __post_init__(self) -> None:
        thresholds = (
            self.low_threshold,
            self.medium_threshold,
            self.high_threshold,
        )
        if not 0 <= thresholds[0] < thresholds[1] < thresholds[2] <= 1:
            raise ValueError("severity thresholds must increase within [0, 1]")
        if self.top_contributions < 1:
            raise ValueError("top_contributions must be positive")
        if self.robust_top_features < 1:
            raise ValueError("robust_top_features must be positive")
        if self.isolation_estimators < 1:
            raise ValueError("isolation_estimators must be positive")

    def as_dict(self, model_name: str) -> dict[str, object]:
        """Return only parameters that determine the selected detector."""
        if model_name not in SUPPORTED_DETECTORS:
            raise ValueError(f"unsupported detector: {model_name}")
        common: dict[str, object] = {
            "low_threshold": self.low_threshold,
            "medium_threshold": self.medium_threshold,
            "high_threshold": self.high_threshold,
            "top_contributions": self.top_contributions,
            "score_normalization": "empirical_percentile",
        }
        if model_name == "robust":
            common.update(
                {
                    "aggregation": "mean_largest_absolute_robust_z",
                    "robust_top_features": self.robust_top_features,
                }
            )
        else:
            common.update(
                {
                    "isolation_estimators": self.isolation_estimators,
                    "isolation_max_samples": self.isolation_max_samples,
                    "isolation_contamination": self.isolation_contamination,
                    "random_state": self.random_state,
                    "contribution_method": "replace_one_feature_with_baseline",
                }
            )
        return common


@dataclass(frozen=True)
class DetectionScores:
    """Scores and per-feature contribution strengths in input row order."""

    raw_scores: np.ndarray
    normalized_scores: np.ndarray
    contribution_strengths: np.ndarray


def _validate_vectors(feature_vectors: np.ndarray) -> np.ndarray:
    vectors = np.asarray(feature_vectors, dtype="float64")
    if vectors.ndim != 2:
        raise ValueError("feature_vectors must be a two-dimensional array")
    if vectors.shape[1] == 0:
        raise ValueError("feature_vectors must contain at least one feature")
    if not np.isfinite(vectors).all():
        raise ValueError("feature_vectors must contain only finite values")
    return vectors


def _empirical_percentiles(values: np.ndarray) -> np.ndarray:
    """Map values to stable average-rank percentiles from zero to one."""
    values = np.asarray(values, dtype="float64")
    count = len(values)
    if count == 0:
        return np.empty(0, dtype="float64")
    if count == 1:
        return np.zeros(1, dtype="float64")
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(count, dtype="float64")
    start = 0
    while start < count:
        end = start + 1
        while end < count and values[order[end]] == values[order[start]]:
            end += 1
        average_rank = (start + end - 1) / 2
        ranks[order[start:end]] = average_rank
        start = end
    return ranks / (count - 1)


def _robust_scores(vectors: np.ndarray, config: DetectionConfig) -> DetectionScores:
    strengths = np.abs(vectors)
    top_count = min(config.robust_top_features, vectors.shape[1])
    largest = np.partition(strengths, -top_count, axis=1)[:, -top_count:]
    raw_scores = largest.mean(axis=1)
    return DetectionScores(
        raw_scores=raw_scores,
        normalized_scores=_empirical_percentiles(raw_scores),
        contribution_strengths=strengths,
    )


def _isolation_scores(
    vectors: np.ndarray,
    config: DetectionConfig,
) -> DetectionScores:
    model = IsolationForest(
        n_estimators=config.isolation_estimators,
        max_samples=config.isolation_max_samples,
        contamination=config.isolation_contamination,
        random_state=config.random_state,
        n_jobs=1,
    )
    model.fit(vectors)
    raw_scores = -model.score_samples(vectors)
    strengths = np.zeros_like(vectors)
    for feature_index in range(vectors.shape[1]):
        at_baseline = vectors.copy()
        at_baseline[:, feature_index] = 0.0
        baseline_scores = -model.score_samples(at_baseline)
        strengths[:, feature_index] = np.maximum(raw_scores - baseline_scores, 0.0)

    no_positive_effect = strengths.sum(axis=1) == 0
    strengths[no_positive_effect] = np.abs(vectors[no_positive_effect])
    return DetectionScores(
        raw_scores=raw_scores,
        normalized_scores=_empirical_percentiles(raw_scores),
        contribution_strengths=strengths,
    )


def score_feature_vectors(
    feature_vectors: np.ndarray,
    model_name: str,
    config: DetectionConfig | None = None,
) -> DetectionScores:
    """Fit the requested detector and score every supplied feature vector."""
    if model_name not in SUPPORTED_DETECTORS:
        raise ValueError(f"unsupported detector: {model_name}")
    active_config = config or DetectionConfig()
    vectors = _validate_vectors(feature_vectors)
    if len(vectors) == 0:
        return DetectionScores(
            raw_scores=np.empty(0, dtype="float64"),
            normalized_scores=np.empty(0, dtype="float64"),
            contribution_strengths=np.empty_like(vectors),
        )
    if model_name == "robust":
        return _robust_scores(vectors, active_config)
    return _isolation_scores(vectors, active_config)
