from datetime import datetime, timedelta, timezone
import sys
from types import SimpleNamespace

from flask import Flask

import govuk_ai_accelerator_app as app_module
from scripts.pipeline import task_manager


def _queue_test_app(tmp_path):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'queue-test.db'}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app_module.db.init_app(app)
    with app.app_context():
        app_module.db.drop_all()
        app_module.db.create_all()
    return app


def test_sqlite_is_treated_as_single_leader_mode(tmp_path):
    app = _queue_test_app(tmp_path)

    with app.app_context():
        leader_connection = task_manager._try_acquire_leader_connection(app_module.db)

    assert leader_connection is True


def test_maintenance_runs_under_advisory_lock_in_sqlite(tmp_path, monkeypatch):
    monkeypatch.setattr(task_manager, "PROGRESS_TIMEOUT", timedelta(minutes=10))
    app = _queue_test_app(tmp_path)
    now = datetime.now(timezone.utc)

    with app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="old-stale-job",
                status="running",
                domain="pip",
                claimed_by="dead-pod",
                claimed_at=now - timedelta(minutes=20),
                last_progress_at=now - timedelta(minutes=20),
                created_at=now - timedelta(minutes=21),
            )
        )
        app_module.db.session.commit()

        task_manager._try_run_maintenance(app, app_module.db)

        job = app_module.db.session.get(app_module.ProcessingJob, "old-stale-job")

    assert job.status == "pending"
    assert job.claimed_by is None


def test_two_pods_claim_different_jobs(tmp_path):
    app = _queue_test_app(tmp_path)
    now = datetime.now(timezone.utc)

    with app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="job-1",
                status="pending",
                domain="pip",
                config_data='{"domain_name": "pip"}',
                domain_prompt="prompt",
                created_at=now - timedelta(seconds=2),
            )
        )
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="job-2",
                status="pending",
                domain="pip",
                config_data='{"domain_name": "pip"}',
                domain_prompt="prompt",
                created_at=now - timedelta(seconds=1),
            )
        )
        app_module.db.session.commit()

        first = task_manager.claim_next_pending_job(
            db=app_module.db,
            job_model=app_module.ProcessingJob,
            worker_id="pod-a",
        )
        second = task_manager.claim_next_pending_job(
            db=app_module.db,
            job_model=app_module.ProcessingJob,
            worker_id="pod-b",
        )

    assert first["job_id"] == "job-1"
    assert second["job_id"] == "job-2"


def test_claim_next_pending_job_sets_progress_fields(tmp_path):
    app = _queue_test_app(tmp_path)

    with app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="pending-job",
                status="pending",
                domain="pip",
                config_data='{"domain_name": "pip"}',
                domain_prompt="prompt",
                created_at=datetime.now(timezone.utc),
            )
        )
        app_module.db.session.commit()

        claimed_job = task_manager.claim_next_pending_job(
            db=app_module.db,
            job_model=app_module.ProcessingJob,
            worker_id="pod-a",
        )

        job = app_module.db.session.get(app_module.ProcessingJob, "pending-job")

    assert claimed_job == {
        "job_id": "pending-job",
        "pipeline": "ontology",
        "domain": "pip",
        "config_data": {"domain_name": "pip"},
        "domain_prompt": "prompt",
        "attempt_count": 1,
    }

    assert job.status == "running"
    assert job.claimed_by == "pod-a"
    assert job.claimed_at is not None
    assert job.last_progress_at is not None
    assert job.attempt_count == 1


def test_claim_next_pending_job_returns_pipeline(tmp_path):
    app = _queue_test_app(tmp_path)

    with app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="pending-harness-job",
                status="pending",
                pipeline="ontology-harness",
                domain="ontology-harness-baseline",
                config_data='{"domain_name": "ontology-harness-baseline"}',
                created_at=datetime.now(timezone.utc),
            )
        )
        app_module.db.session.commit()

        claimed_job = task_manager.claim_next_pending_job(
            db=app_module.db,
            job_model=app_module.ProcessingJob,
            worker_id="pod-a",
        )

    assert claimed_job["pipeline"] == "ontology-harness"


def test_run_claimed_job_dispatches_ontology_harness(monkeypatch):
    calls = []

    def record_ontology_call(config_data, domain_prompt, job_id, attempt_count=None, worker_id=None):
        calls.append(("ontology", config_data, domain_prompt, job_id, attempt_count, worker_id))

    def record_harness_call(config_data, domain_prompt, job_id, attempt_count=None, worker_id=None):
        calls.append(("harness", config_data, domain_prompt, job_id, attempt_count, worker_id))

    monkeypatch.setattr(
        "scripts.pipeline.ontology_generator.run_ontology_background_task",
        record_ontology_call,
    )
    monkeypatch.setitem(
        sys.modules,
        "scripts.pipeline.ontology_harness",
        SimpleNamespace(run_ontology_harness_background_task=record_harness_call),
    )

    task_manager.run_claimed_job(
        app=None,
        worker_id="pod-a",
        claimed_job={
            "job_id": "ontology-harness-baseline:v1",
            "pipeline": "ontology-harness",
            "domain": "ontology-harness-baseline",
            "config_data": {"domain_name": "ontology-harness-baseline"},
            "domain_prompt": None,
            "attempt_count": 1,
        },
    )

    assert calls == [
        (
            "harness",
            {"domain_name": "ontology-harness-baseline"},
            None,
            "ontology-harness-baseline:v1",
            1,
            "pod-a",
        )
    ]


def test_recover_stale_running_jobs_requeues_only_jobs_without_recent_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(task_manager, "PROGRESS_TIMEOUT", timedelta(minutes=10))
    app = _queue_test_app(tmp_path)
    now = datetime.now(timezone.utc)

    with app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="stale-job",
                status="running",
                domain="pip",
                claimed_by="pod-a",
                claimed_at=now - timedelta(minutes=20),
                last_progress_at=now - timedelta(minutes=20),
                created_at=now - timedelta(minutes=21),
            )
        )
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="fresh-job",
                status="running",
                domain="pip",
                claimed_by="pod-b",
                claimed_at=now - timedelta(minutes=2),
                last_progress_at=now - timedelta(minutes=1),
                created_at=now - timedelta(minutes=3),
            )
        )
        app_module.db.session.commit()

        task_manager.recover_stale_running_jobs(app)

        stale_job = app_module.db.session.get(app_module.ProcessingJob, "stale-job")
        fresh_job = app_module.db.session.get(app_module.ProcessingJob, "fresh-job")

    assert stale_job.status == "pending"
    assert stale_job.claimed_by is None
    assert stale_job.claimed_at is None

    assert fresh_job.status == "running"
    assert fresh_job.claimed_by == "pod-b"


def test_mark_job_failed_if_still_running_clears_lease(tmp_path):
    app = _queue_test_app(tmp_path)
    now = datetime.now(timezone.utc)

    with app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="failed-future-job",
                status="running",
                domain="pip",
                claimed_by="pod-a",
                claimed_at=now - timedelta(minutes=1),
                heartbeat_at=now - timedelta(seconds=30),
                last_progress_at=now - timedelta(seconds=30),
                created_at=now - timedelta(minutes=2),
            )
        )
        app_module.db.session.commit()

        updated = task_manager.mark_job_failed_if_still_running(
            db=app_module.db,
            job_model=app_module.ProcessingJob,
            job_id="failed-future-job",
            error_message="Pipeline task failed: boom",
        )

        job = app_module.db.session.get(app_module.ProcessingJob, "failed-future-job")

    assert updated is True
    assert job.status == "failed"
    assert job.error_message == "Pipeline task failed: boom"
    assert job.claimed_by is None
    assert job.claimed_at is None
    assert job.heartbeat_at is None


def test_mark_job_failed_if_still_running_leaves_completed_job_alone(tmp_path):
    app = _queue_test_app(tmp_path)

    with app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="completed-job",
                status="completed",
                domain="pip",
                job_runs="run-20260518-1",
                created_at=datetime.now(timezone.utc),
            )
        )
        app_module.db.session.commit()

        updated = task_manager.mark_job_failed_if_still_running(
            db=app_module.db,
            job_model=app_module.ProcessingJob,
            job_id="completed-job",
            error_message="Pipeline task failed: late callback",
        )

        job = app_module.db.session.get(app_module.ProcessingJob, "completed-job")

    assert updated is False
    assert job.status == "completed"
    assert job.error_message is None
    assert job.job_runs == "run-20260518-1"


def test_handle_finished_job_future_marks_running_job_failed(tmp_path):
    app = _queue_test_app(tmp_path)

    class FailedFuture:
        def exception(self):
            return RuntimeError("boom")

    with app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="callback-job",
                status="running",
                domain="pip",
                claimed_by="pod-a",
                created_at=datetime.now(timezone.utc),
            )
        )
        app_module.db.session.commit()

    task_manager.handle_finished_job_future(
        app=app,
        worker_id="pod-a",
        claimed_job={"job_id": "callback-job", "domain": "pip"},
        future=FailedFuture(),
    )

    with app.app_context():
        job = app_module.db.session.get(app_module.ProcessingJob, "callback-job")

    assert job.status == "failed"
    assert job.error_message == "Pipeline task failed: boom"
    assert job.claimed_by is None


def test_recover_stale_marks_failed_at_max_attempts(tmp_path, monkeypatch):
    app = _queue_test_app(tmp_path)
    monkeypatch.setattr(task_manager, "PROGRESS_TIMEOUT", timedelta(minutes=10))
    monkeypatch.setattr(task_manager, "MAX_JOB_ATTEMPTS", 2)
    now = datetime.now(timezone.utc)

    with app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="exhausted-job",
                status="running",
                domain="pip",
                claimed_by="pod-a",
                attempt_count=2,
                claimed_at=now - timedelta(minutes=20),
                last_progress_at=now - timedelta(minutes=20),
                created_at=now - timedelta(minutes=21),
            )
        )
        app_module.db.session.commit()

        task_manager.recover_stale_running_jobs(app)

        job = app_module.db.session.get(app_module.ProcessingJob, "exhausted-job")

    assert job.status == "failed"
    assert job.claimed_by is None
    assert "attempts" in (job.error_message or "")


def test_recover_stale_requeues_below_max_attempts(tmp_path, monkeypatch):
    app = _queue_test_app(tmp_path)
    monkeypatch.setattr(task_manager, "PROGRESS_TIMEOUT", timedelta(minutes=10))
    monkeypatch.setattr(task_manager, "MAX_JOB_ATTEMPTS", 2)
    now = datetime.now(timezone.utc)

    with app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="retry-job",
                status="running",
                domain="pip",
                claimed_by="pod-a",
                attempt_count=1,
                claimed_at=now - timedelta(minutes=20),
                last_progress_at=now - timedelta(minutes=20),
                created_at=now - timedelta(minutes=21),
            )
        )
        app_module.db.session.commit()

        task_manager.recover_stale_running_jobs(app)

        job = app_module.db.session.get(app_module.ProcessingJob, "retry-job")

    assert job.status == "pending"
    assert job.claimed_by is None


def test_progress_timeout_env_parsing(monkeypatch):
    monkeypatch.setenv("PROGRESS_TIMEOUT_MINUTES", "30")
    assert task_manager._progress_timeout() == timedelta(minutes=30)

    monkeypatch.setenv("PROGRESS_TIMEOUT_MINUTES", "not-a-number")
    assert task_manager._progress_timeout() == timedelta(minutes=45)

    monkeypatch.delenv("PROGRESS_TIMEOUT_MINUTES", raising=False)
    assert task_manager._progress_timeout() == timedelta(minutes=45)


def test_max_job_attempts_env_parsing(monkeypatch):
    monkeypatch.setenv("MAX_JOB_ATTEMPTS", "5")
    assert task_manager._max_job_attempts() == 5

    monkeypatch.setenv("MAX_JOB_ATTEMPTS", "bad")
    assert task_manager._max_job_attempts() == 2

    monkeypatch.delenv("MAX_JOB_ATTEMPTS", raising=False)
    assert task_manager._max_job_attempts() == 2
