from datetime import datetime, timedelta, timezone

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
        "config_data": {"domain_name": "pip"},
        "domain_prompt": "prompt",
    }
    assert job.status == "running"
    assert job.claimed_by == "pod-a"
    assert job.claimed_at is not None
    assert job.last_progress_at is not None
    assert job.attempt_count == 1


def test_recover_stale_running_jobs_requeues_only_jobs_without_recent_progress(tmp_path):
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
