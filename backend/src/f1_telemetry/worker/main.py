"""Redis Queue worker process."""

import logging

from rq import Queue, Worker

from f1_telemetry.core.config import get_settings
from f1_telemetry.core.redis import create_redis_connection

logger = logging.getLogger(__name__)


def main() -> None:
    """Process FastF1 import jobs until the worker receives a stop signal."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    connection = create_redis_connection(settings)
    queue = Queue(settings.import_queue_name, connection=connection)
    worker = Worker([queue], connection=connection)
    logger.info("Worker listening on queue %s", settings.import_queue_name)
    worker.work(logging_level=settings.log_level)


if __name__ == "__main__":
    main()
