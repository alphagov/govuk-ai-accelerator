import logging
import os
import sys
import time
from contextlib import contextmanager
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


def _format_context(context: dict) -> str:
    if not context:
        return ""
    return " " + " ".join(f"{key}={value}" for key, value in context.items())


@contextmanager
def log_step(starting: str, completed: str, **context):
    ctx = _format_context(context)
    logger.debug(f"{starting}…{ctx}")
    start = time.monotonic()
    try:
        yield
    except Exception as exc:
        logger.error(f"Error {starting[0].lower() + starting[1:]}{ctx}: {exc}")
        raise
    elapsed = time.monotonic() - start
    logger.info(f"Successfully {completed} in {elapsed:.1f}s{ctx}")


__all__ = ["logger", "configure_logging", "UtcIsoFormatter", "log_step"]
