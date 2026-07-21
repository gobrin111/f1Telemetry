"""Shared settings tests."""

import pytest
from pydantic import ValidationError

from f1_telemetry.core.config import Settings


def test_default_settings_match_local_browser_workflow() -> None:
    settings = Settings(_env_file=None)

    assert settings.api_port == 8000
    assert settings.web_origin == "http://localhost:3000"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.redis_url == "redis://:redis_dev@localhost:6379/0"


def test_invalid_api_port_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(api_port=70_000, _env_file=None)
