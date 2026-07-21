"""Environment-backed application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration shared by the API and worker processes."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="F1_",
        extra="ignore",
    )

    app_name: str = "F1 Telemetry"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    web_origin: str = "http://localhost:3000"
    database_url: str = (
        "postgresql+psycopg://f1telemetry:f1telemetry_dev@localhost:5432/f1telemetry"
    )
    redis_url: str = "redis://:redis_dev@localhost:6379/0"
    data_dir: Path = Path("data")
    fastf1_cache_dir: Path = Path("data/fastf1-cache")
    import_dir: Path = Path("data/imports")
    import_queue_name: str = "session-imports"
    import_job_timeout_seconds: int = Field(default=3600, ge=60)
    import_result_ttl_seconds: int = Field(default=604800, ge=3600)


@lru_cache
def get_settings() -> Settings:
    """Load and cache settings once per process."""
    return Settings()
