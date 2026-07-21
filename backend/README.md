# Backend

The backend contains the shared Python package used by the FastAPI web process
and the background worker.

## Commands

After installing the development dependencies from the repository README:

```bash
f1-api
f1-worker
pytest
ruff check .
ruff format --check .
```

The worker listens to the Redis `session-imports` queue and processes FastF1
race-session imports. Imported Parquet artifacts and the FastF1 cache are stored
under the configured data directory.
