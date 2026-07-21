"""FastAPI application factory and development entry point."""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis

from f1_telemetry.api.routes.health import router as health_router
from f1_telemetry.api.routes.imports import router as imports_router
from f1_telemetry.core.config import Settings, get_settings
from f1_telemetry.core.redis import create_redis_connection


def create_app(
    settings: Settings | None = None,
    redis_connection: Redis | None = None,
) -> FastAPI:
    """Create an application with explicit settings for easy testing."""
    active_settings = settings or get_settings()

    application = FastAPI(
        title=active_settings.app_name,
        version="0.1.0",
        description="API for F1 telemetry anomaly detection.",
    )
    application.state.settings = active_settings
    application.state.redis = redis_connection or create_redis_connection(
        active_settings
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[active_settings.web_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(imports_router, prefix="/api/v1")

    return application


app = create_app()


def run() -> None:
    """Run the API using the configured host and port."""
    settings = get_settings()
    uvicorn.run(
        "f1_telemetry.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower(),
    )
