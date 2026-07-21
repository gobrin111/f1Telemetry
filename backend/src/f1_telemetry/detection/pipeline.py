"""Database orchestration for reproducible lap anomaly analyses."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
from sqlalchemy import delete, select

from f1_telemetry.detection.calculator import (
    DETECTOR_VERSIONS,
    DetectionConfig,
    score_feature_vectors,
)
from f1_telemetry.storage.database import (
    create_database_engine,
    create_session_factory,
)
from f1_telemetry.storage.models import (
    AnomalyResult,
    FeatureRun,
    LapFeature,
    ModelRun,
    RaceSession,
)


@dataclass(frozen=True)
class AnalysisSummary:
    """Stable summary for a new or existing completed analysis run."""

    model_run_id: int
    feature_run_id: int
    session_key: str
    model_name: str
    model_version: str
    row_count: int
    scored_count: int
    severity_counts: dict[str, int]


@dataclass(frozen=True)
class _FeatureInput:
    lap_id: int
    eligible: bool
    exclusion_reason: str | None
    feature_values: dict[str, Any]
    feature_vector: list[float] | None


def _configuration_hash(
    feature_run: FeatureRun,
    model_name: str,
    config: DetectionConfig,
) -> tuple[str, dict[str, object]]:
    parameters = config.as_dict(model_name)
    identity = {
        "feature_run_id": feature_run.id,
        "feature_schema_version": feature_run.schema_version,
        "feature_names": feature_run.feature_names,
        "model_name": model_name,
        "model_version": DETECTOR_VERSIONS[model_name],
        "parameters": parameters,
    }
    serialized = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest(), parameters


def _severity(score: float, config: DetectionConfig) -> str | None:
    if score >= config.high_threshold:
        return "high"
    if score >= config.medium_threshold:
        return "medium"
    if score >= config.low_threshold:
        return "low"
    return None


def _contributions(
    feature_names: list[str],
    feature_values: dict[str, Any],
    vector: list[float],
    strengths: np.ndarray,
    model_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    raw_values = feature_values.get("raw", {})
    baselines = feature_values.get("baselines", {})
    scales = feature_values.get("scales", {})
    order = np.argsort(-strengths, kind="stable")[:limit]
    total = float(strengths[order].sum())
    method = (
        "absolute_robust_z"
        if model_name == "robust"
        else "replace_feature_with_historical_baseline"
    )
    output: list[dict[str, Any]] = []
    for index in order:
        normalized_name = feature_names[int(index)]
        raw_name = normalized_name.removesuffix("_robust_z")
        strength = float(strengths[int(index)])
        observed = raw_values.get(raw_name)
        baseline = baselines.get(raw_name)
        normalized = float(vector[int(index)])
        output.append(
            {
                "feature": raw_name,
                "observed_value": observed,
                "baseline_value": baseline,
                "baseline_scale": scales.get(raw_name),
                "normalized_deviation": normalized,
                "direction": "above" if normalized >= 0 else "below",
                "contribution": strength,
                "contribution_fraction": strength / total if total > 0 else 0.0,
                "method": method,
            }
        )
    return output


def _metrics(scores: np.ndarray, severities: list[str | None]) -> dict[str, Any]:
    severity_counts = {
        severity: severities.count(severity) for severity in ("low", "medium", "high")
    }
    if len(scores) == 0:
        return {
            "score_summary": None,
            "severity_counts": severity_counts,
            "anomaly_count": 0,
        }
    return {
        "score_summary": {
            "minimum": float(scores.min()),
            "mean": float(scores.mean()),
            "median": float(np.median(scores)),
            "p90": float(np.quantile(scores, 0.90)),
            "p97": float(np.quantile(scores, 0.97)),
            "p995": float(np.quantile(scores, 0.995)),
            "maximum": float(scores.max()),
        },
        "severity_counts": severity_counts,
        "anomaly_count": sum(severity_counts.values()),
    }


def _summary(run: ModelRun, session_key: str) -> AnalysisSummary:
    counts = (run.metrics or {}).get("severity_counts", {})
    return AnalysisSummary(
        model_run_id=run.id,
        feature_run_id=int(run.feature_run_id),
        session_key=session_key,
        model_name=run.model_name,
        model_version=run.model_version,
        row_count=run.row_count,
        scored_count=run.scored_count,
        severity_counts={
            severity: int(counts.get(severity, 0))
            for severity in ("low", "medium", "high")
        },
    )


def build_session_analysis(
    *,
    database_url: str,
    session_key: str,
    model_name: str,
    feature_run_id: int | None = None,
    config: DetectionConfig | None = None,
    force: bool = False,
) -> AnalysisSummary:
    """Fit, score, explain, and persist one detector against one feature run."""
    active_config = config or DetectionConfig()
    model_version = DETECTOR_VERSIONS.get(model_name)
    if model_version is None:
        raise ValueError(f"unsupported detector: {model_name}")
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    model_run_id: int | None = None
    try:
        with factory.begin() as db:
            race_session = db.scalar(
                select(RaceSession).where(RaceSession.session_key == session_key)
            )
            if race_session is None:
                raise LookupError(f"session not found: {session_key}")
            feature_statement = select(FeatureRun).where(
                FeatureRun.session_id == race_session.id,
                FeatureRun.status == "completed",
            )
            if feature_run_id is not None:
                feature_statement = feature_statement.where(
                    FeatureRun.id == feature_run_id
                )
            feature_run = db.scalar(
                feature_statement.order_by(
                    FeatureRun.completed_at.desc(), FeatureRun.id.desc()
                )
            )
            if feature_run is None:
                raise LookupError(f"completed feature run not found: {session_key}")
            config_hash, parameters = _configuration_hash(
                feature_run, model_name, active_config
            )
            existing = db.scalar(
                select(ModelRun).where(
                    ModelRun.feature_run_id == feature_run.id,
                    ModelRun.model_name == model_name,
                    ModelRun.model_version == model_version,
                    ModelRun.config_hash == config_hash,
                )
            )
            if existing is not None and existing.status == "completed" and not force:
                return _summary(existing, session_key)
            if existing is None:
                existing = ModelRun(
                    session_id=race_session.id,
                    feature_run_id=feature_run.id,
                    job_id=(
                        f"analysis-{feature_run.id}-{model_name}-{config_hash[:16]}"
                    ),
                    model_name=model_name,
                    model_version=model_version,
                    feature_schema_version=feature_run.schema_version,
                    config_hash=config_hash,
                    parameters=parameters,
                    status="running",
                    row_count=0,
                    scored_count=0,
                    started_at=datetime.now(UTC),
                )
                db.add(existing)
                db.flush()
            else:
                existing.status = "running"
                existing.started_at = datetime.now(UTC)
                existing.completed_at = None
                existing.error = None
                existing.metrics = None
            model_run_id = existing.id
            selected_feature_run_id = feature_run.id
            feature_names = list(feature_run.feature_names)

        with factory() as db:
            stored_rows = db.scalars(
                select(LapFeature)
                .where(LapFeature.feature_run_id == selected_feature_run_id)
                .order_by(LapFeature.lap_id)
            ).all()
            inputs = [
                _FeatureInput(
                    lap_id=row.lap_id,
                    eligible=row.eligible,
                    exclusion_reason=row.exclusion_reason,
                    feature_values=row.feature_values,
                    feature_vector=row.feature_vector,
                )
                for row in stored_rows
            ]

        eligible = [row for row in inputs if row.eligible]
        if any(row.feature_vector is None for row in eligible):
            raise ValueError("eligible feature rows must contain a feature vector")
        vectors = np.asarray(
            [row.feature_vector for row in eligible],
            dtype="float64",
        ).reshape(len(eligible), len(feature_names))
        scored = score_feature_vectors(vectors, model_name, active_config)
        severities = [
            _severity(float(score), active_config) for score in scored.normalized_scores
        ]
        score_by_lap = {
            row.lap_id: (index, float(scored.normalized_scores[index]))
            for index, row in enumerate(eligible)
        }
        results: list[AnomalyResult] = []
        for row in inputs:
            scored_lap = score_by_lap.get(row.lap_id)
            if scored_lap is None:
                results.append(
                    AnomalyResult(
                        model_run_id=model_run_id,
                        lap_id=row.lap_id,
                        eligible=False,
                        exclusion_reason=row.exclusion_reason,
                    )
                )
                continue
            index, score = scored_lap
            severity = severities[index]
            vector = row.feature_vector
            if vector is None:
                raise RuntimeError("eligible vector disappeared during analysis")
            results.append(
                AnomalyResult(
                    model_run_id=model_run_id,
                    lap_id=row.lap_id,
                    eligible=True,
                    exclusion_reason=None,
                    score=score,
                    severity=severity,
                    is_anomaly=severity is not None,
                    contributions=_contributions(
                        feature_names,
                        row.feature_values,
                        vector,
                        scored.contribution_strengths[index],
                        model_name,
                        active_config.top_contributions,
                    ),
                )
            )

        run_metrics = _metrics(scored.normalized_scores, severities)
        run_metrics["raw_score_summary"] = (
            {
                "minimum": float(scored.raw_scores.min()),
                "mean": float(scored.raw_scores.mean()),
                "maximum": float(scored.raw_scores.max()),
            }
            if len(scored.raw_scores)
            else None
        )
        with factory.begin() as db:
            run = db.get(ModelRun, model_run_id)
            if run is None:
                raise RuntimeError(f"model run disappeared: {model_run_id}")
            db.execute(
                delete(AnomalyResult).where(AnomalyResult.model_run_id == model_run_id)
            )
            db.add_all(results)
            run.status = "completed"
            run.row_count = len(inputs)
            run.scored_count = len(eligible)
            run.metrics = run_metrics
            run.completed_at = datetime.now(UTC)
            run.error = None
            db.flush()
            return _summary(run, session_key)
    except Exception as error:
        if model_run_id is not None:
            with factory.begin() as db:
                run = db.get(ModelRun, model_run_id)
                if run is not None:
                    run.status = "failed"
                    run.error = f"{type(error).__name__}: {error}"[:1000]
                    run.completed_at = datetime.now(UTC)
        raise
    finally:
        engine.dispose()
