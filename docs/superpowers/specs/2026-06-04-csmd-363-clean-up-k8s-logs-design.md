# CSMD-363 — Clean up Kubernetes logs

- **Date:** 2026-06-04
- **Repo:** `govuk-ai-accelerator`
- **Branch:** `csmd-363-clean-up-k8s-logs`

## Problem

During an active run the Kubernetes logs are dominated by repeated, low-value
polling messages, which makes the real job lifecycle hard to follow during an
incident. Two sources dominate:

- **Worker-slot polling** — when every executor slot is busy the task-manager
  loop logs `[queue] no free worker slots on worker=…` at `info` **every 1
  second** per pod.
- **Advisory-lock polling** — the queue-leader check logs `advisory lock …
  acquired` / `not acquired` / `released` at `info` **every ~60 seconds** per
  pod.

On top of the volume, the lines themselves are hard to read in Kubernetes. In
production the shared `get_logger()` returns a `RichLogger` (from the
`taxonomy-ontology-accelerator` package) that prints emoji with forced terminal
colours and **no timestamp**, and whose `info()` prints regardless of level.
Flask's `app.logger` separately uses a non-ISO default format. So there is no
consistent, timezone-aware timestamp on app or worker logs.

## Acceptance criteria

- **AC1** — app and worker logs include an ISO-8601 timestamp with timezone, and
  remain readable.
- **AC2** — advisory-lock acquire/release/not-acquired during normal polling is
  debug-level, rate-limited, or otherwise absent from normal info logs.
- **AC3** — `no free worker slots` is not emitted every second at info level
  while all slots are busy.
- **AC4** — job lifecycle events (claimed, starts, progresses, completes, fails,
  stopped) remain visible at info/warning/error as appropriate.
- **AC5** — log lines relating to a job include `job_id` where available, plus
  `domain` and `worker` where relevant.

## Scope

All changes are made in `govuk-ai-accelerator`. The shared
`taxonomy-ontology-accelerator` (`RichLogger`) package is **not** modified — the
service uses only standard level methods on its logger, so it can adopt a
stdlib logger without any change to the shared package. Logs are emitted as
human-readable text (not JSON); there are no Kubernetes/Helm manifest changes
because log configuration lives entirely in the application.

Touched modules: `scripts/pipeline/logging_config.py` (foundation + helpers),
`scripts/pipeline/task_manager.py` (polling de-noise, correlation),
`scripts/pipeline/ontology_generator.py` and
`scripts/pipeline/ontology_harness.py` (three-phase step logging), and
`scripts/ingestion/ingestion_pipeline.py` (same treatment, plus replacing a raw
`print()` and stripping emoji). Emoji are removed from emitted messages so the
Kubernetes logs are plain text.

## Design

### 1. Logging foundation (AC1)

Rework `scripts/pipeline/logging_config.py` to configure standard-library
logging instead of returning a `RichLogger`:

- **`UtcIsoFormatter(logging.Formatter)`** — overrides `formatTime` to return
  `datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds")`,
  producing timestamps such as `2026-06-04T09:12:33.123+00:00`. Line format:
  `"%(asctime)s %(levelname)-7s %(message)s"`.
- **`configure_logging()`** — idempotent. Attaches a single
  `StreamHandler(sys.stdout)` using `UtcIsoFormatter` to the **root** logger and
  sets the level from the `LOG_LEVEL` environment variable (default `INFO`;
  unknown values fall back to `INFO`). Idempotency is guaranteed by naming the
  handler and skipping setup if a handler with that name is already attached.
- **`logger = logging.getLogger("govuk-ai-accelerator")`** — a real stdlib
  logger that propagates to root. All five pipeline modules that import this
  `logger` (`task_manager`, `utils`, `ontology_generator`, `ontology_harness`,
  `__init__`) keep working unchanged and gain timestamps automatically.

`create_flask_app()` calls `configure_logging()` as its **very first statement**,
before the `_cached_app` early-return, before the database initialises, before
the task-manager thread starts, and before any `app.logger` call. It operates on
the root logger, so it takes no `app` argument. Configuring the root logger
before `app.logger` is first accessed means Flask's `has_level_handler` check
finds an existing handler and does not attach its own plain-format
`default_handler` (verified against the installed Flask 3.1.2), so `app.logger`
inherits the ISO-8601 UTC format too. `logger.propagate` stays `True` so records
reach the root handler — and so `caplog` can capture them in tests.

The reworked module keeps a **single** logging configuration path: the
`taxonomy-ontology-accelerator` `get_logger` import and the `basicConfig`
fallback are both removed, so nothing re-formats or double-configures logging.
The production entry point is `waitress-serve` → `create_app` →
`create_asgi_app` → `create_flask_app()`; at that point the root logger is clean,
so our handler is the only one. The local-only `__main__` path (`uvicorn`) also
flows through `create_flask_app()`.

### 2. De-noise advisory-lock polling (AC2)

In `task_manager.py`, drop the four leader-lock lines from `info` to `debug`:

- `[queue] sqlite mode detected; treating this pod as leader`
- `[queue] advisory lock {id} acquired`
- `[queue] advisory lock {id} not acquired`
- `[queue] advisory lock {id} released`

The useful maintenance outcomes — `recovered N stale running jobs` and
`cleaned up N stale jobs` — already fire only when `N > 0` and stay at `info`.

### 3. De-noise worker-slot polling (AC3)

Replace the unconditional per-second line with transition logging driven by a
new pure helper:

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

The worker loop keeps a `was_saturated` local and integrates it:

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

Result: one `info` line when the pool becomes fully busy, one `info` line when a
slot frees up, and `debug` for every repeat in between. Steady-state idle (slots
free, no work) logs nothing here.

`EXECUTOR_MAX_WORKERS` is currently `1`, so the message wording avoids plural
assumptions, and the previous per-second line spanned the entire duration of a
single running job rather than brief contention.

### 4. Keep lifecycle visible (AC4)

All claim/start/return/requeue/stale/fail/stop lines stay at their current
`info`/`warning`/`error` levels. The only demotion is the per-job bookkeeping
line `[job=…] releasing worker slot on worker=…`, which drops to `debug`; the
meaningful signals around it — `execution returned` (`info`) and `worker future
failed` (`error`) — remain.

Per-step lifecycle is enriched by the three-phase logging in §7. Step *starts*
move to `debug`, but each step *completion* logs at `info` (with duration) and
each failure at `error`, while the job-level start and outcome stay at
`info`/`error`. So claimed → started → progressing (per-step completions) →
completed / failed / stopped all remain visible without enabling `debug` (AC4).

### 5. Correlation (AC5)

Most lifecycle lines already carry `[job=…] domain=… worker=…`. Add `domain` and
`worker` to the two lines that currently carry only `job_id`:

- `requeue_claimed_job`: `requeueing after executor submission failure` — add
  `domain={job.domain} worker={job.claimed_by}` (logged before the lease is
  cleared, so both are still set).
- `mark_job_failed_if_still_running`: `marking running job as failed after worker
  failure` — add `domain={job.domain} worker={job.claimed_by}` (same ordering
  guarantee).

### 6. Operator override

`LOG_LEVEL=DEBUG` resurfaces every suppressed advisory-lock and per-poll line
during an incident, with no code redeploy.

### 7. Informative three-phase step logging (AC4, AC5; closes an AC1 gap)

The worker pipelines run as discrete steps, but today each emits only a bare
start line with no job context and no success/failure. They are reworked into a
**three-phase** pattern — *start (debug) → success (info, with duration) → failure
(error)* — with every line tagged by job UUID and domain.

A context-manager helper in `logging_config.py`:

```python
@contextmanager
def log_step(starting, completed, **context):
    ctx = _format_context(context)            # " job=<uuid> domain=visa"
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

`_format_context` renders ` key=value` pairs in call order (job first) or `""`
when empty. The step *start* sits at `debug` so a healthy run stays quiet; only
completions and failures show at `info`/`error`.

**Ontology generation** (`ontology_generator.py`): wrap each of the five steps at
its call site and delete the bare internal start lines —

```python
with log_step("Extracting ontology data", "extracted ontology data", job=job_id, domain=domain):
    pipeline = await _extract_ontology(pipeline)
```

steps: setting up → extracting → processing → creating the graph → saving output.
The stop/supersede checks sit *between* steps, so a stop is never mislabelled as a
step failure. The `_mark_job_progress` log line drops to `debug` (its database
write, used for stale-job recovery, is untouched) because the step-completion line
now carries the visible progress.

**Job level** (the pipeline entry functions, not the dispatcher): reword the
existing start / `completed` / `stopped` / `superseded` / `failed` branches to the
same style with `job` + `domain` + `worker`, keeping their distinct levels
(`stopped` stays `info`, `superseded` stays `warning`, `failed` stays `error`) so
an intentional stop is never logged as an error. The dispatcher bookkeeping lines
in `run_claimed_job` (`execution starting` / `execution returned`) drop to
`debug`, leaving a single clean job-level arc owned by the pipeline module.

**Ingestion** (`ingestion_pipeline.py`): route everything through the shared
`logger` (the stray `print()` becomes `logger.debug`; the `logging.warning` calls
and 🚀/✅/❌ emoji are removed) and give start/complete/fail the same three-phase
wording with `job` + `domain`. Ingestion is one coarse step today; per-command
sub-steps (download, clean) are a possible later extension.

A healthy ontology run then reads as a followable arc at `info` (≈ 7 lines over
several minutes):

```
2026-06-04T09:12:33.101+00:00 INFO    [job=3f2a9c10-…] Generating ontology for domain=visa
2026-06-04T09:12:33.870+00:00 INFO    Successfully set up ontology pipeline in 0.5s job=3f2a9c10-… domain=visa
2026-06-04T09:13:48.700+00:00 INFO    Successfully extracted ontology data in 74.8s job=3f2a9c10-… domain=visa
2026-06-04T09:14:55.110+00:00 INFO    Successfully processed ontology data in 66.4s job=3f2a9c10-… domain=visa
2026-06-04T09:15:10.044+00:00 ERROR   Error creating ontology graph job=3f2a9c10-… domain=visa: <reason>
```

Job IDs are full UUIDs (`str(uuid4())`) on every job/step line, so an operator can
grep a single job end-to-end. Queue-level lines with no job (`worker pool full`,
`task manager thread started`) carry `worker=` instead.

## Test plan (TDD)

Each change is driven by a failing test first, matching the existing style
(`Flask` app on a `sqlite:///tmp_path` database, functions called directly, no
`conftest.py`).

**New `tests/test_logging_config.py`:**

- formatter output timestamp matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00 ` and includes level and message (AC1).
- `configure_logging()` attaches exactly one named handler when called twice (idempotent).
- `configure_logging()` honours `LOG_LEVEL` (e.g. `DEBUG`) and falls back to `INFO` on an unknown value.

**Extend `tests/test_task_manager.py` (using `caplog`):**

- advisory-lock lines are absent at `INFO` and present at `DEBUG` — sqlite line
  via the real sqlite path; the postgres `acquired`/`not acquired`/`released`
  branch via a stubbed connection (`_uses_postgres` → `True`, fake connection
  whose `execute().scalar()` is controlled) (AC2).
- `log_worker_slot_state` covers all four transitions: becomes full → one `INFO`
  containing `worker pool full`; stays full → no `INFO` (a `DEBUG` instead);
  frees up → one `INFO` containing `worker slot free`; stays free → no log. Each
  case scopes its level window with `caplog.at_level(...)` so state does not leak
  across tests (AC3).
- lifecycle levels: `claim` at `INFO`, max-attempts at `WARNING`,
  worker-future-failed at `ERROR` (AC4).
- claim, requeue, and mark-failed messages contain `job=`, `domain=`, and
  `worker=` (AC5).

**Three-phase logging (`log_step`):**

- success path emits a `debug` start line then exactly one `info` line
  `Successfully {completed} in <n>s` carrying `job=` and `domain=` (AC4, AC5).
- failure path emits one `error` line `Error {starting…}: <exc>` and re-raises the
  original exception unchanged (AC4).
- `_format_context` renders `job` first and omits absent fields; `time.monotonic`
  is monkeypatched so the duration string is deterministic.

**Pipeline wiring:**

- a fake `OntologyPipelineBuilder` drives `run_ontology_background_task` and
  asserts each of the five steps logs a completion line with the job UUID and
  domain, and that an exception raised inside a step surfaces as a single
  `Error …` line (AC4, AC5).
- `run_ingestion_background_task` logs start/complete (and failure) through the
  shared `logger` with `job`/`domain`, emits no emoji, and makes no `print()`
  call (AC1, AC5).

## Verified against the code (2026-06-04)

- `EXECUTOR_MAX_WORKERS = 1` (an `int`) — the message renders correctly, and the
  AC3 noise previously covered a whole running job, not just brief contention.
- Flask 3.1.2 is installed and exposes `flask.logging.has_level_handler`, so the
  `app.logger` inheritance approach holds.
- No standalone script imports the pipeline `logger`, `task_manager`, or
  `configure_logging` outside `create_flask_app()` and the tests, so configuring
  inside the app factory is sufficient (the untracked `scripts/analysis/` helper
  does not use it).
- `create_flask_app()` early-returns a cached app, so `configure_logging()` is
  placed on the first line, before the cache check, and is idempotent.
- `logging.StreamHandler` flushes on every record, so stdout logs are not
  buffered or delayed under Kubernetes.
- The service uses only standard level methods on the shared `logger` (zero
  `RichLogger` custom-method calls), so swapping in a stdlib logger breaks
  nothing; `logger.exception(...)` keeps working and now includes a traceback.
- Job IDs are `str(uuid4())` UUIDs, so every job/step line carries the full UUID
  for end-to-end grepping (not the short integers used as placeholders earlier).
- There are three pipelines — `ontology`, `ontology-harness`, and `ingestion`.
  `ingestion_pipeline.py` already receives `job_id` and `domain`, but currently
  uses a raw `print()`, emoji, and `logging.warning`; this work normalises all of
  them onto the shared logger.
- The stop/supersede checks run *between* ontology steps, so wrapping a step in
  `log_step` cannot mislabel an intentional stop as a step failure.

## Risks and notes

- `caplog` captures `LogRecord`s regardless of formatter, so AC1's timestamp is
  asserted against `UtcIsoFormatter` directly rather than via `caplog`.
- Configuring the root logger affects libraries' loggers too; this is intended —
  consistent timestamps across the process — and the level stays `INFO` by
  default.
- No behaviour change to job scheduling, claiming, or recovery; this work is
  limited to log levels, formatting, log routing, and correlation fields.
- `log_step` measures duration with `time.monotonic()`; tests monkeypatch it for
  determinism. Because step *starts* are `debug`, AC4's visible lifecycle rests on
  the `info` step-completions plus the `info`/`error` job-level arc — confirmed to
  cover claimed/started/progressing/completed/failed/stopped.
- Three-phase wrappers catch `Exception` (not `BaseException`), so
  `KeyboardInterrupt`/`SystemExit` propagate untouched.
