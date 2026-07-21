"""Redis connection helpers shared by the API and worker."""

from redis import Redis

from f1_telemetry.core.config import Settings


def create_redis_connection(settings: Settings) -> Redis:
    """Create a binary Redis client compatible with RQ."""
    return Redis.from_url(settings.redis_url, decode_responses=False)
