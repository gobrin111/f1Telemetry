# Lap anomaly detection

## Scope and versions

Phase 7 scores eligible completed-race laps from one exact `lap-features-v1`
feature run. It provides two detector versions:

- `robust` `1.0.0`: an explainable statistical baseline.
- `isolation_forest` `1.0.0`: a deterministic scikit-learn Isolation Forest.

Both consume the same 14 historical robust z-scores. Neither detector assigns
causes or diagnoses failures; a high score only means that the lap differs from
its earlier driver, compound, stint, and track-condition comparison history.

## Scoring

The robust detector takes the mean of the three largest absolute z-scores. This
allows either one very large deviation or several moderate deviations to raise
a lap's raw score.

Isolation Forest fits 300 trees to all eligible vectors in the selected
completed feature run with random seed `42`. Its negated `score_samples` value
is the raw anomaly score. The model is session-specific and unsupervised; it
does not use anomaly labels.

For either detector, raw scores are converted to deterministic empirical-rank
percentiles from `0` to `1`. This makes the two models comparable and gives the
UI a stable score contract, but it is a within-run rank rather than a calibrated
probability. Severity bands are:

- Low: score at least `0.90` and below `0.97`.
- Medium: score at least `0.97` and below `0.995`.
- High: score at least `0.995`.

Scores below `0.90` are normal results and have no severity. The thresholds are
review cutoffs, not claims of statistical significance.

## Explanations

Each scored lap stores its five strongest contributions with the feature's raw
observed value, historical raw median, robust scale, normalized deviation,
direction, and contribution strength.

For the robust detector, contribution strength is the absolute robust z-score.
For Isolation Forest, each feature is replaced with its historical baseline
(`z = 0`) and the decrease in model anomaly score is measured. This is a local
perturbation explanation. It indicates which inputs supported the score, not a
causal effect or a global tree feature importance.

## Reproducibility and storage

`model_runs` stores the exact feature-run reference, detector and feature-schema
versions, parameters, configuration hash, status, row counts, score metrics,
and timestamps. `anomaly_results` stores exactly one row per source lap. Every
eligible lap receives a score and every excluded lap carries forward its
machine-readable exclusion reason.

The feature run, detector/version, feature ordering, and parameters form the
idempotency key. An identical request returns the completed run. `--force`
rebuilds its results without creating duplicates.

## Evaluation

The automated evaluation creates 300 seeded normal 14-feature vectors and 10
injected multivariate anomalies with large timing, speed, throttle, and braking
deviations. Both detector versions place all 10 injected cases in their top 10,
and repeated runs produce identical normalized scores. This test verifies basic
sensitivity and reproducibility; it is not evidence of real-world precision.

Both models must also be reviewed on the same stored real-session feature run.
That review compares overlap in the highest-ranked laps and checks that the
recorded contributions are plausible observed-versus-baseline deviations.

### Bahrain 2024 review

The first real-session review used the stored 2024 Bahrain Grand Prix race,
feature run `3` (pipeline `1.2.0`): 1,129 total laps, 820 eligible, and 309
excluded. Both model runs scored all 820 eligible laps and retained a reason for
every excluded lap. Repeating the command returned the same model-run IDs.

The normalized score correlation was `0.814`. The models shared 6 of their top
10 laps, 13 of their top 25, and 56 of the 82 laps in the review bands. This is
useful behavior for the MVP: the statistical model supplies a transparent
baseline, while Isolation Forest adds a different multivariate ranking without
being unrelated to that baseline.

Both models ranked Nico Hülkenberg's lap 38 first. Its Isolation Forest
explanation showed a 100.08-second lap against a 96.75-second historical
baseline, slower first and third sectors, lower mean speed, and lower mean
throttle. Those values are internally coherent evidence of an unusual lap, but
they do not establish why it happened. Other high rankings similarly exposed
large sector, speed, throttle, or RPM deviations. The review therefore confirms
that stored explanations are understandable while reinforcing the need for
telemetry charts and race context in later phases.

## Known limitations and likely false positives

- Percentile scoring always highlights the highest-ranked fraction in a large
  run even when the session contains no meaningful incident.
- Isolation Forest is fitted on the full completed session, so its distribution
  includes laps occurring after the lap being scored. Historical feature
  normalization itself remains free of future information.
- Traffic, evolving tire behavior, fuel load, minor weather movement, track
  evolution, and sparse comparison groups can look unusual without representing
  a driving or mechanical problem.
- FastF1 timing, telemetry, flags, and weather may contain gaps or corrections.
- Per-lap summaries can hide short corner-level events and do not align traces
  by distance; that deeper investigation belongs to later UI phases.
- Local perturbation contributions describe model sensitivity around one input.
  Correlated features such as lap and sector times can split or duplicate the
  apparent importance.
