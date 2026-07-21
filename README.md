# f1Telemetry

F1 Telemetry is a browser-based application for importing completed Formula 1
race sessions, detecting unusual lap-level performance, and investigating the
telemetry behind each result.

The current product definition and acceptance criteria are in the
[MVP product specification](docs/MVP_SPEC.md).

## Repository layout

```text
backend/   Shared Python package for the FastAPI API and background worker
frontend/  Next.js browser application
docs/      Product and architecture documentation
```

The API and worker intentionally share one Python package. This lets ingestion,
feature, and model code be reused while the processes remain independently
runnable.

## Requirements

- Python 3.12
- Node.js 24 and npm 11
- Docker Desktop with WSL integration for Phase 3 and later

## Local setup

Copy the example configuration before starting either application:

```bash
cp .env.example .env
```

Install and check the backend:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e './backend[dev]'
.venv/bin/ruff check backend
.venv/bin/ruff format --check backend
.venv/bin/pytest backend
```

Start the API at <http://localhost:8000>:

```bash
.venv/bin/f1-api
```

Its health endpoint is <http://localhost:8000/api/v1/health>, and its OpenAPI
documentation is <http://localhost:8000/docs>.

In another terminal, install and start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000> to use the browser application.

Run all frontend checks from `frontend/`:

```bash
npm run lint
npm run format
npm test
npm run build
```

Run the import worker after installing the backend and starting PostgreSQL and
Redis:

```bash
.venv/bin/f1-worker
```

It listens for FastF1 import jobs on the configured Redis queue and exits
cleanly on `Ctrl+C`.

## Docker development environment

Docker Compose is the recommended way to run the complete local stack. Copy the
example environment file once, then build and start every service:

```bash
cp .env.example .env
docker compose up --build
```

Open the browser application at <http://localhost:3000>. The API is available
at <http://localhost:8000>, with interactive documentation at
<http://localhost:8000/docs>.

The stack includes:

- `frontend`: Next.js development server with browser hot reload.
- `api`: FastAPI development server with Python source reload.
- `worker`: Redis Queue worker for FastF1 race-session imports.
- `migrate`: one-shot Alembic migration run before the API and worker start.
- `postgres`: PostgreSQL with a persistent named volume.
- `redis`: Redis with append-only persistence in a named volume.

Check container status and health:

```bash
docker compose ps
docker compose logs --follow api worker frontend
```

Stop the containers without deleting stored database or Redis data:

```bash
docker compose down
```

The default credentials in `.env.example` are for local development only. Use
different secrets before exposing or deploying any service.

## Import a completed race

Queue an import by year and round number:

```bash
curl -X POST http://localhost:8000/api/v1/imports \
  -H 'Content-Type: application/json' \
  -d '{"year": 2024, "round_number": 1}'
```

The response contains a deterministic job ID such as
`import-2024-round-01-race`. Use it to check progress:

```bash
curl http://localhost:8000/api/v1/imports/import-2024-round-01-race
```

Submitting the same race again returns the existing job or completed artifact
instead of downloading duplicate data. To retry a failed job, submit the same
request with `"retry_failed": true`.

Successful imports normalize event, session, driver, result, lap, stint, and
weather records into PostgreSQL. Driver telemetry remains in compressed
Parquet files referenced from PostgreSQL. See the
[storage architecture](docs/STORAGE.md) for the schema, artifact layout, and
retry behavior.

## Database migrations

Docker Compose applies pending migrations automatically through the one-shot
`migrate` service. To apply them manually from the repository:

```bash
cd backend
../.venv/bin/alembic upgrade head
```

Create future schema changes with Alembic rather than calling SQLAlchemy's
`create_all` in application code.
