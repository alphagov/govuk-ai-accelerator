import logging
import os
import sys
from datetime import datetime, timezone

_HANDLER_NAME = "govuk-ai-accelerator-stdout"
_LINE_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"


class UtcIsoFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        )


def configure_logging() -> None:
    root = logging.getLogger()

    level = logging.getLevelName(os.getenv("LOG_LEVEL", "INFO").upper())
    if not isinstance(level, int):
        level = logging.INFO
    root.setLevel(level)

    if any(getattr(h, "name", None) == _HANDLER_NAME for h in root.handlers):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(UtcIsoFormatter(_LINE_FORMAT))
    root.addHandler(handler)


logger = logging.getLogger("govuk-ai-accelerator")

__all__ = ["logger", "configure_logging", "UtcIsoFormatter"]
