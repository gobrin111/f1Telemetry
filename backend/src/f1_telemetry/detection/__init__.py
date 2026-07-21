"""Versioned lap-level anomaly detection."""

from f1_telemetry.detection.calculator import (
    DETECTOR_VERSIONS,
    SUPPORTED_DETECTORS,
    DetectionConfig,
    DetectionScores,
    score_feature_vectors,
)

__all__ = [
    "DETECTOR_VERSIONS",
    "SUPPORTED_DETECTORS",
    "DetectionConfig",
    "DetectionScores",
    "score_feature_vectors",
]
