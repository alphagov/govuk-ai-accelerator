import logging
import re

from scripts.pipeline import logging_config


ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00 ")


def _format_one(record_level=logging.INFO, msg="hello"):
    formatter = logging_config.UtcIsoFormatter("%(asctime)s %(levelname)-7s %(message)s")
    record = logging.LogRecord(
        name="govuk-ai-accelerator",
        level=record_level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    return formatter.format(record)


def test_formatter_emits_iso8601_utc_timestamp():
    line = _format_one()
    assert ISO_TS.match(line), line
    assert "INFO" in line
    assert line.rstrip().endswith("hello")


def test_configure_logging_is_idempotent(monkeypatch):
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [], raising=False)
    logging_config.configure_logging()
    logging_config.configure_logging()
    named = [h for h in root.handlers if getattr(h, "name", None) == "govuk-ai-accelerator-stdout"]
    assert len(named) == 1


def test_configure_logging_honours_log_level(monkeypatch):
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [], raising=False)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    logging_config.configure_logging()
    assert root.level == logging.DEBUG


def test_configure_logging_falls_back_to_info_on_bad_level(monkeypatch):
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [], raising=False)
    monkeypatch.setenv("LOG_LEVEL", "NONSENSE")
    logging_config.configure_logging()
    assert root.level == logging.INFO
