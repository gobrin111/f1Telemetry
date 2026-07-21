"""Signal-aware worker process scaffold."""

import logging
import signal
from threading import Event
from types import FrameType

from f1_telemetry.core.config import get_settings

logger = logging.getLogger(__name__)


def main() -> None:
    """Run an idle worker until queue integration is added in a later phase."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    stop_requested = Event()

    def request_stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("Worker received signal %s and is stopping", signum)
        stop_requested.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    logger.info("Worker scaffold started; queue integration will be added in Phase 4")
    while not stop_requested.wait(settings.worker_poll_interval_seconds):
        logger.debug("Worker scaffold heartbeat")


if __name__ == "__main__":
    main()
