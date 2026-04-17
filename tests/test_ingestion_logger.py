"""Tests for the shared ingestion logger's handler lifecycle."""
import io
import logging

import pytest

from scripts.ingestion.commands.utils import get_logger


@pytest.fixture(autouse=True)
def _reset_logger():
    """Strip handlers before and after each test so singleton state can't leak."""
    logger = logging.getLogger("ontology-ingestion")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    yield
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)


def test_second_call_with_new_stream_redirects_log_output_to_new_buffer():
    """Simulates two consecutive ingestion jobs — each must log to its own buffer."""
    buf1 = io.StringIO()
    logger_a = get_logger(stream=buf1)
    logger_a.info("first run")

    buf2 = io.StringIO()
    logger_b = get_logger(stream=buf2)
    logger_b.info("second run")

    assert "second run" in buf2.getvalue(), "second run should reach the new buffer"
    assert "second run" not in buf1.getvalue(), "second run must not leak to stale buffer"


def test_plain_get_logger_after_stream_setup_keeps_writing_to_stream():
    """Inside a run, commands call get_logger() with no args; output must still stream."""
    buf = io.StringIO()
    get_logger(stream=buf)

    # Mimics download/extract/clean calling the module-level helper.
    inner_logger = get_logger()
    inner_logger.info("during-run message")

    assert "during-run message" in buf.getvalue()
