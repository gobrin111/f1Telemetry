"""API scaffold tests."""

import asyncio

import httpx
from fastapi import FastAPI

from f1_telemetry.api.main import create_app
from f1_telemetry.core.config import Settings


def get(app: FastAPI, path: str) -> httpx.Response:
    """Send a request directly to the ASGI app without opening a socket."""

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


def test_health_endpoint_reports_test_environment() -> None:
    app = create_app(Settings(environment="test"))

    response = get(app, "/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "api",
        "environment": "test",
    }


def test_openapi_document_has_versioned_health_route() -> None:
    app = create_app(Settings(environment="test"))

    document = get(app, "/openapi.json").json()

    assert document["info"]["title"] == "F1 Telemetry"
    assert "/api/v1/health" in document["paths"]
