# Storage architecture

## Purpose

Phase 5 separates data by access pattern. PostgreSQL stores normalized records
that the API, feature pipeline, and model pipeline need to filter or join.
High-volume telemetry samples remain in Zstandard-compressed Parquet because
they are read in contiguous lap or driver slices and would add millions of
rows to the relational database for each race.

## Relational schema

The initial migration creates these groups of tables:

- `events` and `sessions` identify a FastF1 race using a unique season/round
  pair and a canonical session key.
- `drivers`, `results`, `laps`, `stints`, and `weather_samples` contain the
  normalized session data. Driver identity is global; result, lap, and stint
  rows retain their session-specific team and performance context.
- `imports` records the source FastF1 version, manifest schema, artifact
  location, row counts, job ID, and completion time for each session.
- `telemetry_files` references one compressed Parquet file per session driver,
  including its relative path, row count, byte size, and SHA-256 checksum.
- `model_runs` and `anomaly_results` reserve the versioned, traceable storage
  needed by Phases 6 and 7 without choosing a model implementation early.

Foreign keys use cascading deletes for records that have no meaning outside a
session or model run. Natural uniqueness constraints prevent duplicate imports,
results, laps, stints, telemetry references, and anomaly results.

## Artifact layout and references

Every imported race has a stable key such as `2024-round-01-race`. Files are
organized under the configured `F1_IMPORT_DIR`:

```text
2024-round-01-race/
  manifest.json
  laps.parquet
  results.parquet
  stints.parquet
  weather.parquet
  telemetry/
    VER.parquet
    PER.parquet
```

Database paths are deliberately relative. The `imports.artifact_path` value is
the session key and each `telemetry_files.relative_path` is relative to that
directory. A deployment can therefore move or mount the data directory at a
different absolute path without rewriting database rows. The checksum and row
count allow the application to detect a missing or changed telemetry artifact.

## Import transaction

The worker first creates the complete Parquet artifact atomically, then loads
its small normalized tables in one database transaction. A database failure
rolls back all relational rows while leaving the immutable artifact available
for a retry. A repeated request is complete only when both the manifest and the
database import record exist, so artifacts created before Phase 5 are
automatically backfilled instead of incorrectly treated as fully imported.

## Migrations and persistence

Alembic owns the database schema. Docker Compose runs `alembic upgrade head` in
a one-shot `migrate` service before starting the API and worker. PostgreSQL and
the import directory use named volumes, so normalized data and telemetry files
survive container replacement and ordinary `docker compose down` operations.
