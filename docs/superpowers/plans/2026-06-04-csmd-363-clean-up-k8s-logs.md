# CSMD-363 Clean up Kubernetes logs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the govuk-ai-accelerator Kubernetes logs followable during an incident — consistent ISO-8601 UTC timestamps, no per-second/per-minute polling spam, and an informative three-phase (start → success → error) arc per job and per pipeline step, all correlated by job UUID, domain, and worker.

**Architecture:** Replace the `RichLogger` returned by the shared `taxonomy-ontology-accelerator` package with a standard-library logger configured once at app startup (ISO-8601 UTC formatter on the root logger, level from `LOG_LEVEL`). Add two small helpers — `log_step` (three-phase context manager) and `log_worker_slot_state` (saturation transition logger). Then adjust call sites across the task manager and the ontology / harness / ingestion pipelines to demote polling noise to `debug`, keep lifecycle at `info`/`warning`/`error`, and tag every job line with `job`/`domain`/`worker`.

**Tech Stack:** Python 3.13, Flask 3.1, stdlib `logging`, pytest (`caplog`), SQLAlchemy, run under `waitress-serve`.

**Spec:** `docs/superpowers/specs/2026-06-04-csmd-363-clean-up-k8s-logs-design.md`

---

## File Structure

- `scripts/pipeline/logging_config.py` — **rewritten.** Owns the stdlib logging foundation (`UtcIsoFormatter`, `configure_logging`, the `logger` instance) and the two helpers (`log_step`, `_format_context`). Single responsibility: how the service logs.
- `govuk_ai_accelerator_app.py` — **modified.** Calls `configure_logging()` as the first line of `create_flask_app()`.
- `scripts/pipeline/task_manager.py` — **modified.** Advisory-lock lines → `debug`; new `log_worker_slot_state` + loop integration; correlation fields + bookkeeping demotions.
- `scripts/pipeline/ontology_generator.py` — **modified.** Wrap the five pipeline steps with `log_step`; reword job-level lines; demote `_mark_job_progress` log.
- `scripts/pipeline/ontology_harness.py` — **modified.** Reword harness outcome lines with `job`/`domain`.
- `scripts/ingestion/ingestion_pipeline.py` — **modified.** Route the K8s lifecycle through the shared `logger`; remove `print()`s and emoji.
- `tests/test_logging_config.py` — **created.** Unit tests for the foundation + helpers.
- `tests/test_task_manager.py` — **extended.** Advisory/slot/correlation tests.
- `tests/test_ontology_logging.py` — **created.** Three-phase pipeline + ingestion log tests.

Test command throughout: `uv run pytest <path> -v` (or `pytest <path> -v` inside the activated `.venv`).

---

## Task 1: Logging foundation — ISO-8601 UTC stdlib logger

**Files:**
- Modify: `scripts/pipeline/logging_config.py` (whole file)
- Modify: `govuk_ai_accelerator_app.py` (import + first line of `create_flask_app`)
- Test: `tests/test_logging_config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_logging_config.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_logging_config.py -v`
Expected: FAIL — `AttributeError: module 'scripts.pipeline.logging_config' has no attribute 'UtcIsoFormatter'` (and `configure_logging`).

- [ ] **Step 3: Rewrite `scripts/pipeline/logging_config.py`**

Replace the entire file with:

```python
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
```

- [ ] **Step 4: Wire `configure_logging()` into app startup**

In `govuk_ai_accelerator_app.py`, add the import alongside the existing pipeline import (near line 21, `from scripts.pipeline.task_manager import start_task_manager`):

```python
from scripts.pipeline.logging_config import configure_logging
```

Then make it the first statement of `create_flask_app()` (currently lines 385-388):

```python
def create_flask_app():
    global _cached_app
    configure_logging()
    if _cached_app:
        return _cached_app
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_logging_config.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Run the existing suite to confirm nothing broke**

Run: `uv run pytest tests/test_task_manager.py tests/test_govuk_ai_accelerator_app.py -q`
Expected: PASS (the swap from `RichLogger` to a stdlib logger is transparent — only standard level methods are used).

- [ ] **Step 7: Commit**

```bash
git add scripts/pipeline/logging_config.py govuk_ai_accelerator_app.py tests/test_logging_config.py
git commit -m "CSMD-363 Add ISO-8601 UTC logging configuration"
```

---

## Task 2: Three-phase `log_step` helper

**Files:**
- Modify: `scripts/pipeline/logging_config.py`
- Test: `tests/test_logging_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_logging_config.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_logging_config.py -k "log_step or format_context" -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'log_step'`.

- [ ] **Step 3: Add the helper to `scripts/pipeline/logging_config.py`**

Add `import time` and `from contextlib import contextmanager` to the imports, then append before `__all__`:

```python
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
```

Update `__all__` to:

```python
__all__ = ["logger", "configure_logging", "UtcIsoFormatter", "log_step"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_logging_config.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline/logging_config.py tests/test_logging_config.py
git commit -m "CSMD-363 Add three-phase log_step helper"
```

---

## Task 3: Quiet advisory-lock polling (AC2)

**Files:**
- Modify: `scripts/pipeline/task_manager.py:49,59,63,76`
- Test: `tests/test_task_manager.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_task_manager.py` (it already imports `task_manager`, `app_module`, `Flask`, and defines `_queue_test_app`):

```python
import logging


def test_sqlite_leader_line_is_debug_not_info(tmp_path, caplog):
    app = _queue_test_app(tmp_path)
    with app.app_context():
        with caplog.at_level(logging.INFO, logger="govuk-ai-accelerator"):
            task_manager._try_acquire_leader_connection(app_module.db)
        assert not any("sqlite mode" in r.getMessage() for r in caplog.records)
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="govuk-ai-accelerator"):
            task_manager._try_acquire_leader_connection(app_module.db)
        assert any(
            "sqlite mode" in r.getMessage() and r.levelno == logging.DEBUG
            for r in caplog.records
        )


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeConnection:
    def __init__(self, acquired):
        self._acquired = acquired
        self.closed = False

    def execute(self, *args, **kwargs):
        return _FakeScalarResult(self._acquired)

    def close(self):
        self.closed = True


def test_postgres_advisory_lines_are_debug(monkeypatch, caplog):
    monkeypatch.setattr(task_manager, "_uses_postgres", lambda db: True)
    fake_conn = _FakeConnection(acquired=True)
    fake_db = type("DB", (), {"engine": type("E", (), {"connect": lambda self: fake_conn})()})()
    with caplog.at_level(logging.DEBUG, logger="govuk-ai-accelerator"):
        conn = task_manager._try_acquire_leader_connection(fake_db)
        task_manager._release_leader_connection(conn)
    messages = [(r.levelno, r.getMessage()) for r in caplog.records]
    assert all(level == logging.DEBUG for level, msg in messages if "advisory lock" in msg)
    assert any("acquired" in msg for _, msg in messages)
    assert any("released" in msg for _, msg in messages)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_task_manager.py -k "advisory or sqlite_leader" -v`
Expected: FAIL — the lines are still emitted at `INFO`.

- [ ] **Step 3: Demote the four lines to `debug`**

In `scripts/pipeline/task_manager.py`, change `logger.info` to `logger.debug` on these four lines:

- Line 49: `logger.debug("[queue] sqlite mode detected; treating this pod as leader")`
- Line 59: `logger.debug(f"[queue] advisory lock {LEADER_LOCK_ID} acquired")`
- Line 63: `logger.debug(f"[queue] advisory lock {LEADER_LOCK_ID} not acquired")`
- Line 76: `logger.debug(f"[queue] advisory lock {LEADER_LOCK_ID} released")`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_task_manager.py -k "advisory or sqlite_leader" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline/task_manager.py tests/test_task_manager.py
git commit -m "CSMD-363 Quiet advisory-lock polling logs"
```

---

## Task 4: Worker-slot saturation on transition (AC3)

**Files:**
- Modify: `scripts/pipeline/task_manager.py` (new function + worker loop lines 311, 327-330)
- Test: `tests/test_task_manager.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_task_manager.py`:

```python
def test_log_worker_slot_state_becomes_full(caplog):
    with caplog.at_level(logging.INFO, logger="govuk-ai-accelerator"):
        result = task_manager.log_worker_slot_state(
            saturated=True, was_saturated=False, worker_id="W1", max_workers=1
        )
    assert result is True
    info = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info) == 1 and "worker pool full" in info[0].getMessage()


def test_log_worker_slot_state_stays_full_is_quiet(caplog):
    with caplog.at_level(logging.INFO, logger="govuk-ai-accelerator"):
        task_manager.log_worker_slot_state(
            saturated=True, was_saturated=True, worker_id="W1", max_workers=1
        )
    assert not [r for r in caplog.records if r.levelno == logging.INFO]


def test_log_worker_slot_state_frees_up(caplog):
    with caplog.at_level(logging.INFO, logger="govuk-ai-accelerator"):
        result = task_manager.log_worker_slot_state(
            saturated=False, was_saturated=True, worker_id="W1", max_workers=1
        )
    assert result is False
    info = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info) == 1 and "worker slot free" in info[0].getMessage()


def test_log_worker_slot_state_stays_free_is_silent(caplog):
    with caplog.at_level(logging.DEBUG, logger="govuk-ai-accelerator"):
        result = task_manager.log_worker_slot_state(
            saturated=False, was_saturated=False, worker_id="W1", max_workers=1
        )
    assert result is False
    assert not caplog.records
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_task_manager.py -k worker_slot_state -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'log_worker_slot_state'`.

- [ ] **Step 3: Add the function and remove the import-time noise line**

In `scripts/pipeline/task_manager.py`, add this module-level function (e.g. just below `_release_leader_connection`):

```python
def log_worker_slot_state(*, saturated, was_saturated, worker_id, max_workers) -> bool:
    became_full = saturated and not was_saturated
    freed_up = was_saturated and not saturated
    if became_full:
        logger.info(f"[queue] worker pool full ({max_workers} busy) worker={worker_id}")
    elif freed_up:
        logger.info(f"[queue] worker slot free worker={worker_id}")
    elif saturated:
        logger.debug(f"[queue] worker pool still full worker={worker_id}")
    return saturated
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `uv run pytest tests/test_task_manager.py -k worker_slot_state -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Integrate into the worker loop**

In `scripts/pipeline/task_manager.py`, initialise the flag next to the other loop locals (currently lines 311-312):

```python
        last_cleanup = 0.0
        cleanup_interval = 60
        was_saturated = False
```

Replace the per-second block (currently lines 327-330):

```python
                if not slots.acquire(blocking=False):
                    logger.info(f"[queue] no free worker slots on worker={worker_id}")
                    time.sleep(1)
                    continue
```

with:

```python
                acquired = slots.acquire(blocking=False)
                was_saturated = log_worker_slot_state(
                    saturated=not acquired,
                    was_saturated=was_saturated,
                    worker_id=worker_id,
                    max_workers=EXECUTOR_MAX_WORKERS,
                )
                if not acquired:
                    time.sleep(1)
                    continue
```

- [ ] **Step 6: Run the whole task-manager suite**

Run: `uv run pytest tests/test_task_manager.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/pipeline/task_manager.py tests/test_task_manager.py
git commit -m "CSMD-363 Log worker-slot saturation on transition"
```

---

## Task 5: Job correlation + bookkeeping demotions (AC4, AC5)

**Files:**
- Modify: `scripts/pipeline/task_manager.py` (lines 209, 224, 235-238, 256-259, 363-365)
- Test: `tests/test_task_manager.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_task_manager.py`:

```python
def _seed_running_job(app, job_id="JID-5", domain="visa", worker="W1"):
    with app.app_context():
        job = app_module.ProcessingJob(
            id=job_id, status="running", domain=domain, claimed_by=worker
        )
        app_module.db.session.add(job)
        app_module.db.session.commit()
    return job_id


def test_requeue_log_includes_domain_and_worker(tmp_path, caplog):
    app = _queue_test_app(tmp_path)
    job_id = _seed_running_job(app)
    with app.app_context():
        with caplog.at_level(logging.INFO, logger="govuk-ai-accelerator"):
            task_manager.requeue_claimed_job(
                db=app_module.db, job_model=app_module.ProcessingJob, job_id=job_id
            )
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert f"job={job_id}" in msg and "domain=visa" in msg and "worker=W1" in msg


def test_mark_failed_log_includes_domain_and_worker(tmp_path, caplog):
    app = _queue_test_app(tmp_path)
    job_id = _seed_running_job(app)
    with app.app_context():
        with caplog.at_level(logging.INFO, logger="govuk-ai-accelerator"):
            task_manager.mark_job_failed_if_still_running(
                db=app_module.db,
                job_model=app_module.ProcessingJob,
                job_id=job_id,
                error_message="boom",
            )
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "domain=visa" in msg and "worker=W1" in msg
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_task_manager.py -k "requeue_log or mark_failed_log" -v`
Expected: FAIL — current messages carry only `job=`.

- [ ] **Step 3: Add correlation fields and demote bookkeeping lines**

In `scripts/pipeline/task_manager.py`:

Line 209 — `requeue_claimed_job` (the `job` row is fetched just above):

```python
    logger.info(
        f"[job={job_id}] requeueing after executor submission failure "
        f"domain={job.domain} worker={job.claimed_by}"
    )
```

Line 224 — `mark_job_failed_if_still_running`:

```python
    logger.info(
        f"[job={job_id}] marking running job as failed after worker failure "
        f"domain={job.domain} worker={job.claimed_by}"
    )
```

Lines 235-238 — demote the dispatcher's start line in `run_claimed_job` from `info` to `debug`:

```python
    logger.debug(
        f"[job={claimed_job['job_id']}] execution starting "
        f"worker={worker_id} domain={claimed_job['domain']} attempt={claimed_job['attempt_count']}"
    )
```

Lines 256-259 — demote the dispatcher's return line from `info` to `debug`:

```python
    logger.debug(
        f"[job={claimed_job['job_id']}] execution returned "
        f"worker={worker_id} domain={claimed_job['domain']}"
    )
```

Lines 363-365 — demote the per-job bookkeeping line from `info` to `debug`:

```python
                logger.debug(
                    f"[job={claimed_job['job_id']}] releasing worker slot on worker={worker_id}"
                )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_task_manager.py -k "requeue_log or mark_failed_log" -v`
Expected: PASS.

- [ ] **Step 5: Run the whole task-manager suite**

Run: `uv run pytest tests/test_task_manager.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/pipeline/task_manager.py tests/test_task_manager.py
git commit -m "CSMD-363 Add job context to task manager logs"
```

---

## Task 6: Three-phase logging in the ontology pipeline (AC4, AC5)

**Files:**
- Modify: `scripts/pipeline/ontology_generator.py` (lines 54, 125, 165, 175, 187, 192, 200, 211, 140-160, 390)
- Test: `tests/test_ontology_logging.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ontology_logging.py`:

```python
import logging
import types

from scripts.pipeline import ontology_generator as og


class _FakeState:
    incremental = False
    output_dir = "/tmp/out"


class _FakePipeline:
    def __init__(self):
        self.state = _FakeState()

    def setup_pipeline(self, **kwargs):
        return self

    def load_existing(self):
        return self

    async def extract_async(self):
        return self

    async def deduplicate(self):
        return self

    async def build_relations(self):
        return self

    async def update_schema(self):
        return self

    async def merge(self):
        return self

    def validate(self):
        return self

    def save(self):
        return self

    def export(self):
        return self

    async def finalize(self):
        return None


def _fake_configs(config):
    ontology_config = types.SimpleNamespace(filesystem=types.SimpleNamespace(protocol="file"))
    pipeline_config = types.SimpleNamespace(
        domain_name="visa", input_path="in", output_dir="out", prompt_path="p"
    )
    return ontology_config, pipeline_config


def test_pipeline_logs_three_phase_per_step(monkeypatch, caplog):
    monkeypatch.setattr(og, "load_config_for_domain", lambda config: _fake_configs(config))
    monkeypatch.setattr(og.fsspec, "filesystem", lambda protocol: object())
    monkeypatch.setattr(og, "_save_version_info", lambda *a, **k: None)
    monkeypatch.setattr(og, "_persist_config_yaml", lambda *a, **k: None)
    monkeypatch.setattr(og, "_finalize_job_status", lambda *a, **k: None)
    monkeypatch.setattr(og, "_mark_job_progress", lambda *a, **k: None)
    monkeypatch.setattr(og, "_raise_if_job_stopped", lambda *a, **k: None)
    monkeypatch.setattr(og, "_raise_if_superseded", lambda *a, **k: None)

    import taxonomy_ontology_accelerator.ontology_engine.pipeline_builder as pb

    monkeypatch.setattr(pb, "OntologyPipelineBuilder", lambda **kwargs: _FakePipeline())

    with caplog.at_level(logging.INFO, logger="govuk-ai-accelerator"):
        result = og.run_ontology_background_task(
            config={"domain": "visa"},
            domain_prompt="",
            job_id="JID-1",
            attempt_count=1,
            worker_id="W1",
        )

    assert result is True
    messages = [r.getMessage() for r in caplog.records]
    assert any("Generating ontology for domain=visa" in m and "job=JID-1" in m for m in messages)
    assert any(
        "Successfully extracted ontology data in" in m and "job=JID-1" in m and "domain=visa" in m
        for m in messages
    )
    assert any(
        "Successfully created ontology graph in" in m and "job=JID-1" in m for m in messages
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_ontology_logging.py -v`
Expected: FAIL — no `Successfully extracted…` / `Generating ontology for domain=…` lines yet.

- [ ] **Step 3: Wrap the five steps with `log_step` and remove the bare start lines**

In `scripts/pipeline/ontology_generator.py`, add the import near the existing `from scripts.pipeline.logging_config import logger`:

```python
from scripts.pipeline.logging_config import log_step, logger
```

Reword the job-level start line (line 125):

```python
    logger.info(
        f"[job={job_id}] Generating ontology for domain={pipeline_config.domain_name} worker={worker_id}"
    )
```

Wrap each step call (lines 140-163). Replace the five `pipeline = …` / `await …` step calls so each is wrapped, keeping the `_mark_job_progress` / `_raise_if_*` calls exactly as they are between them:

```python
    with log_step("Setting up ontology pipeline", "set up ontology pipeline",
                  job=job_id, domain=pipeline_config.domain_name):
        pipeline = _setup_pipeline(pipeline, pipeline_config)
    _mark_job_progress(job_id, "pipeline-setup")
    _raise_if_job_stopped(job_id)
    _raise_if_superseded(job_id, attempt_count, worker_id)

    with log_step("Extracting ontology data", "extracted ontology data",
                  job=job_id, domain=pipeline_config.domain_name):
        pipeline = await _extract_ontology(pipeline)
    _mark_job_progress(job_id, "ontology-extracted")
    _raise_if_job_stopped(job_id)
    _raise_if_superseded(job_id, attempt_count, worker_id)

    with log_step("Processing ontology data", "processed ontology data",
                  job=job_id, domain=pipeline_config.domain_name):
        pipeline = await _process_ontology(pipeline)
    _mark_job_progress(job_id, "ontology-processed")
    _raise_if_job_stopped(job_id)
    _raise_if_superseded(job_id, attempt_count, worker_id)

    with log_step("Creating ontology graph", "created ontology graph",
                  job=job_id, domain=pipeline_config.domain_name):
        pipeline = await _create_ontology_graph(pipeline)
    _mark_job_progress(job_id, "graph-created")
    _raise_if_job_stopped(job_id)
    _raise_if_superseded(job_id, attempt_count, worker_id)

    with log_step("Saving pipeline output", "saved pipeline output",
                  job=job_id, domain=pipeline_config.domain_name):
        await _save_pipeline_output(pipeline, pipeline_config, fs)
    _mark_job_progress(job_id, "artifacts-saved")
    _raise_if_job_stopped(job_id)
    _raise_if_superseded(job_id, attempt_count, worker_id)
```

Reword the job-level completion line (line 165):

```python
    logger.info(
        f"[job={job_id}] Successfully generated ontology for domain={pipeline_config.domain_name} "
        f"worker={worker_id}"
    )
```

Delete the now-redundant bare start lines inside the step helpers — remove `logger.info("Setting up ontology pipeline")` (line 175), `logger.info("Extracting ontology data")` (line 187), `logger.info("Processing ontology data")` (line 192), `logger.info("Creating ontology graph")` (line 200), and `logger.info("Saving pipeline output")` (line 211).

- [ ] **Step 4: Demote the duplicate progress + wrapper success lines to `debug`**

Line 54 — `_mark_job_progress` (keep the DB write above it; only the log changes):

```python
        logger.debug(f"[job={job_id}] progress stage={stage}")
```

Line 390 — `run_ontology_background_task` success (the inner pipeline already logged the visible success at line 165):

```python
        logger.debug(f"[job={job_id}] pipeline task completed successfully")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_ontology_logging.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/pipeline/ontology_generator.py tests/test_ontology_logging.py
git commit -m "CSMD-363 Add three-phase logs to ontology pipeline"
```

---

## Task 7: Tidy ontology harness outcome lines (AC5)

The five generation steps already log via the shared `run_ontology_pipeline` (Task 6), so the harness needs only its own outcome lines reworded to carry `domain`.

**Files:**
- Modify: `scripts/pipeline/ontology_harness.py` (lines 350, 399, 402, 412)
- Test: `tests/test_ontology_logging.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ontology_logging.py`:

```python
from scripts.pipeline import ontology_harness as oh


def test_harness_failure_log_includes_job_and_domain(monkeypatch, caplog):
    def _boom(**kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(oh.asyncio, "run", _boom)
    monkeypatch.setattr(oh, "_finalize_job_status", lambda *a, **k: None)

    with caplog.at_level(logging.ERROR, logger="govuk-ai-accelerator"):
        try:
            oh.run_ontology_harness_background_task(
                config={"domain_name": "visa"},
                domain_prompt="",
                job_id="JID-7",
                attempt_count=1,
                worker_id="W1",
            )
        except RuntimeError:
            pass

    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any("job=JID-7" in m and "domain=visa" in m for m in errors)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_ontology_logging.py -k harness -v`
Expected: FAIL — the failure line carries only `job=` and `error=`.

- [ ] **Step 3: Reword the harness outcome lines**

In `scripts/pipeline/ontology_harness.py`, using `config.get("domain_name", DEFAULT_HARNESS_DOMAIN)` for the domain:

Line 350:

```python
        logger.info(
            f"[job={job_id}] ontology harness generation completed "
            f"domain={config.get('domain_name', DEFAULT_HARNESS_DOMAIN)}"
        )
```

Line 399:

```python
        logger.warning(
            f"[job={job_id}] ontology harness superseded; abandoning "
            f"domain={config.get('domain_name', DEFAULT_HARNESS_DOMAIN)}: {exc}"
        )
```

Line 402:

```python
        logger.info(
            f"[job={job_id}] ontology harness stopped "
            f"domain={config.get('domain_name', DEFAULT_HARNESS_DOMAIN)}: {exc}"
        )
```

Line 412:

```python
        logger.error(
            f"[job={job_id}] ontology harness failed "
            f"domain={config.get('domain_name', DEFAULT_HARNESS_DOMAIN)} error={exc}"
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_ontology_logging.py -k harness -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline/ontology_harness.py tests/test_ontology_logging.py
git commit -m "CSMD-363 Tidy ontology harness log wording"
```

---

## Task 8: Route ingestion lifecycle through the shared logger (AC1, AC5)

The ingestion run keeps its own buffered S3 logger, but its **K8s stdout** must be clean: no raw `print()`, no emoji, ISO-timestamped lifecycle lines tagged with `job`/`domain`.

**Files:**
- Modify: `scripts/ingestion/ingestion_pipeline.py`
- Test: `tests/test_ontology_logging.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ontology_logging.py`:

```python
from scripts.ingestion import ingestion_pipeline as ing


def test_ingestion_logs_lifecycle_through_shared_logger(tmp_path, monkeypatch, caplog, capsys):
    import govuk_ai_accelerator_app as app_module
    from flask import Flask

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'ing.db'}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app_module.db.init_app(app)
    with app.app_context():
        app_module.db.create_all()
        app_module.db.session.add(
            app_module.ProcessingJob(id="ING-1", status="pending", pipeline="ingestion", domain="visa")
        )
        app_module.db.session.commit()

    monkeypatch.setattr(app_module, "create_flask_app", lambda: app)
    monkeypatch.setattr(ing, "load_config", lambda **kwargs: types.SimpleNamespace(final_log_url=None))
    monkeypatch.setattr(ing, "download_content", lambda config: None)
    monkeypatch.setattr(ing, "clean_content", lambda config: None)

    with caplog.at_level(logging.INFO, logger="govuk-ai-accelerator"):
        ing.run_ingestion_background_task(job_id="ING-1", domain="visa")

    messages = [r.getMessage() for r in caplog.records]
    assert any("Running ingestion pipeline" in m and "job=ING-1" in m and "domain=visa" in m for m in messages)
    assert any("Successfully ran ingestion pipeline" in m and "job=ING-1" in m for m in messages)
    assert not any("🚀" in m or "✅" in m or "❌" in m for m in messages)
    assert "DEBUG: Starting ingestion job" not in capsys.readouterr().out
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_ontology_logging.py -k ingestion -v`
Expected: FAIL — the lifecycle goes to `print()`/the buffered logger, not the shared logger.

- [ ] **Step 3: Rework `scripts/ingestion/ingestion_pipeline.py`**

Add the shared logger import at the top (keep the existing imports). The local buffered logger is renamed to `run_log` to avoid shadowing:

```python
from scripts.pipeline.logging_config import logger
```

Replace the body with the shared-logger lifecycle lines, no `print()`, no emoji:

```python
def run_ingestion_background_task(config_path: str = None, config_content: str = None, links_list: list[str] = None, job_id: str = None, domain: str = None):

    from govuk_ai_accelerator_app import db, ProcessingJob, create_flask_app

    app = create_flask_app()

    logger.info(f"[job={job_id}] Running ingestion pipeline domain={domain}")

    with app.app_context():
        if job_id:
            try:
                job = db.session.get(ProcessingJob, job_id)
                if job:
                    job.status = "running"
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.warning(f"[job={job_id}] unable to set running status domain={domain}: {e}")

        config_obj = None
        try:
            config_obj = load_config(config_path=config_path, config_content=config_content, links_list=links_list, domain=domain)

            log_buffer = io.StringIO()
            run_log = get_logger(stream=log_buffer)
            run_log.info(f"Starting ingestion pipeline for job {job_id or 'manual'}")

            download_content(config_obj)
            clean_content(config_obj)

            if job_id:
                try:
                    job = db.session.get(ProcessingJob, job_id)
                    if job:
                        job.status = "completed"
                        db.session.commit()
                        run_log.info(f"Ingestion job {job_id} completed successfully")
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"[job={job_id}] unable to set completed status domain={domain}: {e}")

            logger.info(f"[job={job_id}] Successfully ran ingestion pipeline domain={domain}")

        except Exception as e:
            error_msg = str(e)
            run_log = get_logger()  # fallback if config_obj failed
            run_log.error(f"Ingestion job {job_id or 'unknown'} failed: {error_msg}")
            logger.error(f"[job={job_id}] Error running ingestion pipeline domain={domain}: {error_msg}")
            if job_id:
                try:
                    job = db.session.get(ProcessingJob, job_id)
                    if job:
                        job.status = "failed"
                        job.error_message = error_msg
                        db.session.commit()
                except Exception as db_err:
                    db.session.rollback()
                    logger.warning(f"[job={job_id}] unable to set failed status domain={domain}: {db_err}")
        finally:
            if config_obj and getattr(config_obj, "final_log_url", None):
                try:
                    final_url = config_obj.final_log_url
                    logger.debug(f"[job={job_id}] finalizing ingestion log to {final_url}")

                    fs, fs_path = fsspec.core.url_to_fs(final_url)
                    parent = fs._parent(fs_path)
                    if parent:
                        fs.makedirs(parent, exist_ok=True)
                    with fs.open(fs_path, 'w') as remote_f:
                        remote_f.write(log_buffer.getvalue())
                except Exception as log_err:
                    logger.error(f"[job={job_id}] error finalizing ingestion log file: {log_err}")
```

Remove the now-unused `import logging` if nothing else in the file uses it.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_ontology_logging.py -k ingestion -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/test_logging_config.py tests/test_task_manager.py tests/test_ontology_logging.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/ingestion/ingestion_pipeline.py tests/test_ontology_logging.py
git commit -m "CSMD-363 Route ingestion logs through app logger"
```

---

## Final verification

- [ ] **Run the entire test suite**

Run: `uv run pytest -q`
Expected: PASS (no regressions).

- [ ] **Eyeball a real run if a dev environment is available**

With `ALLOW_IN_MEMORY_DB=true`, start the app and confirm: lines carry ISO-8601 UTC timestamps; no per-second `worker slots` or per-minute `advisory lock` lines at INFO; a job shows a `Generating… → Successfully … in Ns → …` arc tagged with the job UUID and domain. Set `LOG_LEVEL=DEBUG` and confirm the suppressed polling/step-start detail reappears.

---

## Spec coverage check

- **AC1 (ISO-8601 + tz):** Task 1 (`UtcIsoFormatter` + `configure_logging`), Task 8 (ingestion `print()` removed).
- **AC2 (advisory quiet):** Task 3.
- **AC3 (no per-second slot spam):** Task 4.
- **AC4 (lifecycle visible):** Tasks 5, 6, 7 (job arc + per-step completions at info/error).
- **AC5 (job/domain/worker correlation):** Tasks 5, 6, 7, 8.
- **Three-phase + duration + lean levels:** Task 2 (`log_step`), Tasks 6-8 (applied).
- **Operator override (`LOG_LEVEL`):** Task 1.
