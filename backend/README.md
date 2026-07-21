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

The worker is an idle, signal-aware process in Phase 2. Redis-backed job
handling and FastF1 imports will be added in later phases.
