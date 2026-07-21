"""API scaffold tests."""

import asyncio

import fakeredis
import httpx
from fastapi import FastAPI

from f1_telemetry.api.main import create_app
from f1_telemetry.core.config import Settings


def request(
    app: FastAPI,
    method: str,
    path: str,
    **kwargs: object,
) -> httpx.Response:
    """Send a request directly to the ASGI app without opening a socket."""

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(request())


def test_health_endpoint_reports_test_environment() -> None:
    app = create_app(Settings(environment="test"))

    response = request(app, "GET", "/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "api",
        "environment": "test",
    }


def test_openapi_document_has_versioned_health_route() -> None:
    app = create_app(Settings(environment="test"))

    document = request(app, "GET", "/openapi.json").json()

    assert document["info"]["title"] == "F1 Telemetry"
    assert "/api/v1/health" in document["paths"]
    assert "/api/v1/imports" in document["paths"]


def test_import_request_is_idempotently_queued(tmp_path) -> None:
    connection = fakeredis.FakeRedis()
    settings = Settings(
        environment="test",
        import_dir=tmp_path / "imports",
        fastf1_cache_dir=tmp_path / "cache",
        _env_file=None,
    )
    app = create_app(settings, redis_connection=connection)

    first = request(
        app,
        "POST",
        "/api/v1/imports",
        json={"year": 2024, "round_number": 1},
    )
    second = request(
        app,
        "POST",
        "/api/v1/imports",
        json={"year": 2024, "round_number": 1},
    )

    assert first.status_code == 202
    assert first.json()["id"] == "import-2024-round-01-race"
    assert first.json()["status"] == "queued"
    assert second.json()["id"] == first.json()["id"]
    assert connection.llen("rq:queue:session-imports") == 1

    job_status = request(app, "GET", f"/api/v1/imports/{first.json()['id']}")
    assert job_status.status_code == 200
    assert job_status.json()["stage"] == "queued"


def test_missing_import_job_returns_safe_not_found_response() -> None:
    connection = fakeredis.FakeRedis()
    app = create_app(
        Settings(environment="test", _env_file=None),
        redis_connection=connection,
    )

    response = request(app, "GET", "/api/v1/imports/import-missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Import job not found"}
