from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import sys
from typing import Any

from app.config import Settings

_LOGGING_CONFIGURED = False
_STANDARD_ATTRS = set(logging.LogRecord(name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None).__dict__)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            payload[key] = _coerce_json_value(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def configure_logging(settings: Settings) -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    level_name = (settings.log_level or "INFO").upper()
    level = logging._nameToLevel.get(level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    if settings.log_json:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
    root_logger.addHandler(handler)

    logging.getLogger("apscheduler").setLevel(max(level, logging.INFO))
    _LOGGING_CONFIGURED = True


def _coerce_json_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_coerce_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _coerce_json_value(item) for key, item in value.items()}
    return str(value)
