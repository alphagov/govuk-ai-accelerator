# 001. Use a PostgreSQL-backed queue for ontology generation

Date: 2026-06-24

Status: Accepted

Documents decision implemented: 2026-04-02, then hardened on 2026-04-08 and
2026-06-01.

## Context

Ontology generation is a long-running operation. The `/ontology/submit` endpoint
needs to accept a request quickly, return a job ID, and let users track the job
from the UI while the Generator works in the background. A single HTTP request
must not stay open for the whole generation run.

The Workflow app is also deployed in an environment that can run more than one
pod. Queueing therefore has to coordinate workers across pods, survive ordinary
pod restarts, and avoid two pods processing the same ontology request at the
same time. The existing `processing_job` table already held user-visible job
state, so the queueing mechanism needed to keep that state consistent with the
Jobs and Review Ontologies pages.

The Generator pipeline also has shared process-level state in dependencies such
as logging, stdout handling, caches, and `fsspec`. Earlier multi-worker attempts
showed that unconstrained in-process parallelism could produce duplicate runs or
jobs that became stuck. The queueing design therefore had to prefer correctness
and operational simplicity over maximum throughput.

This ADR covers ontology generation jobs and ontology harness jobs dispatched
through `scripts/pipeline/task_manager.py`. Ingestion jobs use the same
`ProcessingJob` model for status tracking, but their direct executor submission
path is outside this decision.

## Decision

Use PostgreSQL as the durable queue by persisting each ontology generation
request as a `processing_job` row with `status = "pending"`.

Each app instance starts a task manager thread unless `DISABLE_TASK_MANAGER=true`
is set. The task manager polls for the oldest pending job, claims it with
`SELECT ... FOR UPDATE SKIP LOCKED`, and changes the row to `running` in the
same transaction. Claiming records:

- `claimed_by`, identifying the pod or host that owns the attempt;
- `claimed_at`, recording when the lease began;
- `last_progress_at`, recording recent Generator progress;
- `attempt_count`, incremented on every claim and used as a fencing token.

Claimed jobs run in the app's bounded in-process executor. The current worker
limit is one job per pod (`EXECUTOR_MAX_WORKERS = 1`) to avoid thread-safety
issues in the Generator's runtime dependencies. More pods can still increase
overall throughput because each pod can claim a different pending row.

The task manager also runs maintenance:

- PostgreSQL advisory lock `420021` elects a single pod to run queue maintenance
  at a time.
- Running jobs with no recent progress are requeued until they reach
  `MAX_JOB_ATTEMPTS`.
- Jobs that exceed the attempt limit are marked failed instead of being retried
  forever.
- Very old pending or running jobs are failed after 24 hours.

Generation code updates `last_progress_at` at pipeline checkpoints. When a
worker finishes, it writes the final job status only if its `attempt_count`
still matches the database row and the job has not been manually stopped. This
prevents a stale attempt from overwriting a newer attempt's status or run ID.

## Considered Alternatives

### Synchronous request processing

Run the Generator inside the `/ontology/submit` request and return only when it
finishes.

This was rejected because ontology generation can run much longer than a normal
web request. It would tie user experience and load balancer behaviour to
pipeline duration, make retries ambiguous, and provide no durable status trail
for the Jobs UI.

### In-memory queue and background threads only

Use Python's in-memory queue or submit directly to the process executor from the
request handler.

This is simple for one local process, but it is not durable. Jobs can disappear
when a pod restarts, and each pod would only know about work submitted to that
pod. It also does not provide safe cross-pod coordination, which is needed when
the app scales horizontally.

### External queue or worker system

Introduce a separate broker and worker system such as Amazon SQS, Celery, RQ, or
another managed queue.

This would provide mature queue features, clearer worker separation, and better
tools for retries and monitoring. It was not selected because it would add
infrastructure, deployment, secrets, local-development setup, and another source
of truth for status. At the current scale, the Workflow app already depends on
PostgreSQL for job state, so a separate queue would add operational complexity
without enough immediate benefit.

### Single queue leader processes all jobs

Elect one pod as a queue leader and let only that pod claim and run jobs.

This reduces duplicate-processing risk, but it underuses extra pods and makes
the leader a throughput bottleneck. The chosen design keeps advisory-lock
leadership only for maintenance and lets every pod claim work safely with row
locks.

### PostgreSQL-backed job table queue

Use the existing `processing_job` table as both the user-visible job log and the
queue.

This was selected because it gives durable job submission, status polling, and
cross-pod coordination with infrastructure the app already requires. PostgreSQL
row locks with `SKIP LOCKED` let multiple pods claim different pending jobs
without central coordination. The trade-off is that queue behaviour now depends
on careful database transitions, polling, lease cleanup, and fencing of stale
attempts.

## Consequences

The queue has at-least-once execution semantics. The system prevents stale
attempts from writing final state, but a worker can still consume compute until
it reaches a progress checkpoint and notices that its attempt has been
superseded or stopped.

PostgreSQL is now part of the critical path for durable ontology processing.
Without a working database, pending jobs cannot be reliably queued, claimed, or
recovered. SQLite remains useful for local tests and development, but production
queue semantics rely on PostgreSQL features such as row locks and advisory
locks.

Throughput scales by adding pods, not by increasing threads inside a pod. That
keeps the Generator safer while its runtime dependencies have shared global
state, but it also means one long job can occupy a pod's worker slot for a long
time.

The queue manager is intentionally small and app-local. This keeps deployment
simple, but it means the team owns queue concerns such as polling interval,
stale-job thresholds, retry limits, and operational observability.

## Revisit This Decision When

- ontology generation volume requires many concurrent workers per pod;
- queue metrics, delayed retries, dead-letter handling, or prioritisation become
  operational requirements;
- the Generator is separated into an independently deployed worker service;
- PostgreSQL load from queue polling or locking becomes material;
- ingestion, harness, and ontology jobs need one unified queue with
  pipeline-specific dispatch and worker pools;
- the Generator dependencies become safe for higher in-process concurrency.

At that point, a managed queue or a dedicated worker framework should be
reconsidered with the current production traffic, failure modes, and operating
model in hand.

## References

- `govuk_ai_accelerator_app.py`: `ProcessingJob`, `/ontology/submit`, app startup,
  and stop/status routes.
- `scripts/pipeline/task_manager.py`: polling, claiming, maintenance, and worker
  execution.
- `scripts/pipeline/ontology_generator.py`: progress updates, stop checks,
  attempt fencing, and final status writes.
- `migrations/versions/c4e92f1b7a10_add_job_leases.py`: lease and attempt-count
  columns.
- `migrations/versions/9f3d7b6a1c21_add_last_progress_at.py`: progress timestamp
  column.
- `tests/test_task_manager.py` and `tests/test_job_fencing.py`: expected queue,
  recovery, and stale-attempt behaviour.
