import logging
import re

import pytest

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


def test_log_step_success_logs_start_debug_and_success_info(monkeypatch, caplog):
    times = iter([100.0, 102.5])
    monkeypatch.setattr(logging_config.time, "monotonic", lambda: next(times))
    with caplog.at_level(logging.DEBUG, logger="govuk-ai-accelerator"):
        with logging_config.log_step(
            "Extracting ontology data", "extracted ontology data", job="JID", domain="visa"
        ):
            pass
    debug = [r for r in caplog.records if r.levelno == logging.DEBUG]
    info = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("Extracting ontology data" in r.getMessage() for r in debug)
    assert len(info) == 1
    msg = info[0].getMessage()
    assert "Successfully extracted ontology data in 2.5s" in msg
    assert "job=JID" in msg and "domain=visa" in msg


def test_log_step_failure_logs_error_and_reraises(caplog):
    with caplog.at_level(logging.DEBUG, logger="govuk-ai-accelerator"):
        with pytest.raises(ValueError, match="boom"):
            with logging_config.log_step("Creating ontology graph", "created ontology graph", job="JID"):
                raise ValueError("boom")
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "Error creating ontology graph job=JID: boom" in errors[0].getMessage()


def test_format_context_orders_job_first_and_skips_when_empty():
    assert logging_config._format_context({}) == ""
    assert logging_config._format_context({"job": "J", "domain": "d"}) == " job=J domain=d"


def test_logger_stays_enabled_after_app_creation_runs_migrations(monkeypatch, caplog):
    monkeypatch.setenv("ALLOW_IN_MEMORY_DB", "true")
    monkeypatch.setenv("DISABLE_TASK_MANAGER", "true")
    import govuk_ai_accelerator_app as app_module

    monkeypatch.setattr(app_module, "_cached_app", None)
    app_module.create_flask_app()

    with caplog.at_level(logging.INFO, logger="govuk-ai-accelerator"):
        logging_config.logger.info("post-migration-line")
    assert any("post-migration-line" in r.getMessage() for r in caplog.records)
