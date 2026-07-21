# Backend

The backend contains the shared Python package used by the FastAPI web process
and the background worker.

## Commands

After installing the development dependencies from the repository README:

```bash
f1-api
f1-features 2024-round-01-race
f1-worker
pytest
ruff check .
ruff format --check .
```

The worker listens to the Redis `session-imports` queue and processes FastF1
race-session imports. Imported Parquet artifacts and the FastF1 cache are stored
under the configured data directory. Normalized session tables and portable
telemetry-file references are stored in PostgreSQL after each artifact import.

`f1-features` reads a stored session and its Parquet telemetry, applies the
versioned eligibility and historical normalization rules, and persists one
feature row per lap. It is idempotent for an unchanged source and configuration.

Run migrations from this directory with:

```bash
alembic upgrade head
```
