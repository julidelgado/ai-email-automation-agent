from __future__ import annotations

from threading import Event
import logging
import signal

from app.config import get_settings
from app.observability import configure_logging
from app.workers.scheduler import SchedulerManager

logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    configure_logging(settings)

    manager = SchedulerManager(settings=settings)
    stop_event = Event()

    def _handle_stop(signum: int, _frame) -> None:
        logger.info("Received stop signal for scheduler process.", extra={"event": "scheduler_signal", "signal": signum})
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    manager.start()
    try:
        while not stop_event.wait(timeout=1.0):
            pass
    finally:
        manager.shutdown()


if __name__ == "__main__":
    main()
