from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask

import govuk_ai_accelerator_app as app_module
from scripts.pipeline import ontology_generator, task_manager


def _fencing_test_app(tmp_path):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'fencing-test.db'}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app_module.db.init_app(app)
    with app.app_context():
        app_module.db.drop_all()
        app_module.db.create_all()
    app_module._cached_app = app
    return app


def _add_job(app, **kwargs):
    defaults = {"status": "running", "domain": "pip", "attempt_count": 1}
    defaults.update(kwargs)
    with app.app_context():
        app_module.db.session.add(app_module.ProcessingJob(**defaults))
        app_module.db.session.commit()


def _get_job(app, job_id):
    with app.app_context():
        return app_module.db.session.get(app_module.ProcessingJob, job_id)


def test_finalize_applies_when_attempt_matches(tmp_path):
    app = _fencing_test_app(tmp_path)
    _add_job(app, id="job-x", attempt_count=2, claimed_by="pod-b")

    applied = ontology_generator._finalize_job_status_if_owner(
        "job-x", "completed", 2, worker_id="pod-b", job_runs="run-owner"
    )

    assert applied is True
    job = _get_job(app, "job-x")
    assert job.status == "completed"
    assert job.job_runs == "run-owner"
    assert job.claimed_by is None


def test_finalize_skipped_when_attempt_superseded(tmp_path):
    app = _fencing_test_app(tmp_path)
    _add_job(app, id="job-x", attempt_count=2, claimed_by="pod-b")

    applied = ontology_generator._finalize_job_status_if_owner(
        "job-x", "completed", 1, worker_id="pod-a", job_runs="run-orphan"
    )

    assert applied is False
    job = _get_job(app, "job-x")
    assert job.status == "running"
    assert job.claimed_by == "pod-b"
    assert job.job_runs is None


def test_finalize_preserves_stopped(tmp_path):
    app = _fencing_test_app(tmp_path)
    _add_job(app, id="job-x", status="stopped", attempt_count=2, claimed_by=None)

    applied = ontology_generator._finalize_job_status_if_owner(
        "job-x", "completed", 2, worker_id="pod-b", job_runs="run-owner"
    )

    assert applied is False
    job = _get_job(app, "job-x")
    assert job.status == "stopped"


def test_raise_if_superseded_raises_when_attempt_bumped(tmp_path):
    app = _fencing_test_app(tmp_path)
    _add_job(app, id="job-x", attempt_count=2, claimed_by="pod-b")

    with pytest.raises(ontology_generator.JobSupersededError):
        ontology_generator._raise_if_superseded("job-x", 1, "pod-a")


def test_raise_if_superseded_noop_when_attempt_matches(tmp_path):
    app = _fencing_test_app(tmp_path)
    _add_job(app, id="job-x", attempt_count=2, claimed_by="pod-b")

    ontology_generator._raise_if_superseded("job-x", 2, "pod-b")


def test_raise_if_superseded_noop_without_token(tmp_path):
    app = _fencing_test_app(tmp_path)
    _add_job(app, id="job-x", attempt_count=2)

    ontology_generator._raise_if_superseded("job-x", None, None)


def test_superseded_background_task_writes_no_status(tmp_path, monkeypatch):
    app = _fencing_test_app(tmp_path)
    _add_job(app, id="job-x", attempt_count=2, claimed_by="pod-b")

    async def fake_pipeline(
        config_data=None, domain_prompt=None, job_id=None, attempt_count=None, worker_id=None
    ):
        ontology_generator._raise_if_superseded(job_id, attempt_count, worker_id)
        return "run-should-not-exist"

    monkeypatch.setattr(ontology_generator, "run_ontology_pipeline", fake_pipeline)

    result = ontology_generator.run_ontology_background_task(
        {"domain_name": "pip"}, "prompt", job_id="job-x", attempt_count=1, worker_id="pod-a"
    )

    assert result is False
    job = _get_job(app, "job-x")
    assert job.status == "running"
    assert job.claimed_by == "pod-b"
    assert job.job_runs is None


def test_finalize_without_attempt_uses_legacy_write(tmp_path):
    app = _fencing_test_app(tmp_path)
    _add_job(app, id="legacy-job", attempt_count=1, claimed_by="pod-a")

    ontology_generator._finalize_job_status(
        "legacy-job", "completed", attempt_count=None, job_runs="run-legacy"
    )

    job = _get_job(app, "legacy-job")
    assert job.status == "completed"
    assert job.job_runs == "run-legacy"
    assert job.claimed_by is None


def test_reaper_requeue_then_reclaim_fences_original(tmp_path, monkeypatch):
    app = _fencing_test_app(tmp_path)
    monkeypatch.setattr(task_manager, "PROGRESS_TIMEOUT", timedelta(minutes=10))
    monkeypatch.setattr(task_manager, "MAX_JOB_ATTEMPTS", 2)
    now = datetime.now(timezone.utc)

    with app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="job-x",
                status="pending",
                domain="pip",
                config_data='{"domain_name": "pip"}',
                domain_prompt="prompt",
                created_at=now - timedelta(minutes=30),
            )
        )
        app_module.db.session.commit()

        claim_a = task_manager.claim_next_pending_job(
            db=app_module.db, job_model=app_module.ProcessingJob, worker_id="pod-a"
        )
        job = app_module.db.session.get(app_module.ProcessingJob, "job-x")
        job.last_progress_at = now - timedelta(minutes=20)
        job.claimed_at = now - timedelta(minutes=20)
        app_module.db.session.commit()

    task_manager.recover_stale_running_jobs(app)

    with app.app_context():
        claim_b = task_manager.claim_next_pending_job(
            db=app_module.db, job_model=app_module.ProcessingJob, worker_id="pod-b"
        )

    assert claim_a["attempt_count"] == 1
    assert claim_b["attempt_count"] == 2

    with pytest.raises(ontology_generator.JobSupersededError):
        ontology_generator._raise_if_superseded("job-x", claim_a["attempt_count"], "pod-a")

    assert (
        ontology_generator._finalize_job_status_if_owner(
            "job-x", "completed", claim_a["attempt_count"], worker_id="pod-a", job_runs="run-orphan"
        )
        is False
    )

    assert (
        ontology_generator._finalize_job_status_if_owner(
            "job-x", "completed", claim_b["attempt_count"], worker_id="pod-b", job_runs="run-owner"
        )
        is True
    )

    final = _get_job(app, "job-x")
    assert final.status == "completed"
    assert final.job_runs == "run-owner"
