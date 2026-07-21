# Lap feature pipeline

## Version and scope

Feature schema `lap-features-v1`, pipeline version `1.1.0`, converts every
stored race lap into either a complete numeric feature vector or one
machine-readable exclusion reason. It uses only information available at or
before the start of the current lap for weather alignment and only earlier
comparable laps for baselines. Phase 7 will consume these vectors; Phase 6 does
not assign anomaly scores.

## Eligibility rules

Rules are evaluated in this order so each lap has one stable primary reason:

1. Pit-out and pit-in laps are excluded.
2. Deleted and FastF1-generated laps are excluded.
3. Laps missing timing, sector, compound, weather, or telemetry data are
   excluded.
4. Laps FastF1 marks inaccurate are excluded.
5. Only a `TrackStatus` of exactly `1` is clear running. Yellow-flag, safety-car,
   virtual-safety-car, and red-flag laps receive distinct exclusion reasons.
6. Laps within the configured stability window after a rainfall transition or
   rapid track-temperature change are excluded.
7. A valid lap needs the configured minimum number of earlier comparison laps.

Wet laps are not automatically invalid. They form a separate comparison group
and become eligible once stable wet running has enough history. This allows a
wet race to be analyzed without comparing it with dry laps.

## Comparison groups and leakage prevention

The comparison key is driver, tire compound, stint, and dry/wet state. This
controls for the largest readily available differences in car/driver pace,
tire type and stint phase, and track condition while retaining enough history
for an MVP baseline. Tire age, lap position, and weather remain explicit
context features.

For every current lap, the pipeline considers only earlier base-valid laps in
the same group. The history is capped at a configurable rolling window. Timing
deltas use the historical median, and normalization uses median/MAD with IQR,
standard deviation, and unit-aware floors as deterministic fallbacks. The
current lap and all future laps are excluded from their own baselines.

Weather is joined with a backward as-of lookup at lap start. Rainfall changes
and track-temperature movement are also derived entirely from past weather
samples.

## Feature vector

Telemetry is summarized per driver and lap from compressed Parquet files:

- Mean and maximum speed.
- Mean throttle and fraction at or above the full-throttle threshold.
- Fraction of samples with braking active.
- Gear-change count.
- Mean RPM.

These values are combined with lap and sector times, tire age, and air/track
temperature. The stored ordered vector contains a historical robust z-score
for every numeric feature. `feature_values` retains raw values, timing deltas,
normalized values, and contextual flags for later explanations.

## Versioned storage

`feature_runs` records the source import, schema and pipeline versions,
configuration hash, ordered feature names, status, and row counts.
`lap_features` stores exactly one row per source lap for that run, including
eligibility, exclusion reason, comparison metadata, values, and vector.

The session, source import, schema version, and configuration hash form an
idempotency key. Repeating an unchanged run returns the existing completed
feature set; `--force` rebuilds it in place. Future model runs reference the
exact `feature_runs` row they consumed.
