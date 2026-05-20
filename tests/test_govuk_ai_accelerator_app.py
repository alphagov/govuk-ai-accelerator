import builtins
import importlib
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask
from werkzeug.test import Client
from werkzeug.wrappers import Response


def _app_module():
    return importlib.import_module("govuk_ai_accelerator_app")


def _client():
    return Client(_app_module().create_app(), Response)


@pytest.fixture(autouse=True)
def _allow_in_memory_db_for_app_tests(monkeypatch):
    monkeypatch.setenv("ALLOW_IN_MEMORY_DB", "true")
    monkeypatch.setenv("DISABLE_TASK_MANAGER", "true")
    app_module = sys.modules.get("govuk_ai_accelerator_app")
    if app_module is not None:
        app_module._cached_app = None
    yield
    app_module = sys.modules.get("govuk_ai_accelerator_app")
    if app_module is not None:
        app_module._cached_app = None


def test_create_app_redirects_visualizer_without_trailing_slash():
    response = _client().get("/visualizer", follow_redirects=False)

    assert response.status_code in {307, 308}
    assert response.headers["Location"].endswith("/visualizer/")


def test_create_app_serves_visualizer_root():
    app_module = _app_module()
    response = _client().get("/visualizer/")

    expected_status = 200 if app_module.VISUALIZER_IMPORT_ERROR is None else 503

    assert response.status_code == expected_status
    assert response.content_type.startswith("text/html")
    if expected_status == 503:
        assert "Visualizer is unavailable" in response.get_data(as_text=True)


def test_create_app_still_serves_ontology_dashboard():
    response = _client().get("/ontology/")

    assert response.status_code == 200


def test_create_flask_app_can_disable_task_manager(monkeypatch):
    app_module = _app_module()
    calls = []

    monkeypatch.setenv("DISABLE_TASK_MANAGER", "true")
    monkeypatch.setattr(app_module, "start_task_manager", lambda app: calls.append(app))

    app_module.create_flask_app()

    assert calls == []


def test_ontology_dashboard_includes_stop_job_action():
    response = _client().get("/ontology/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<th scope="col">Actions</th>' in html
    assert "table-action-link stop-job-action" in html
    assert "Stop<span class=\"govuk-visually-hidden\"> job" in html
    assert "['pending', 'running'].includes(job.status.toLowerCase())" in html


def test_historical_jobs_uses_link_styled_stop_job_action():
    response = _client().get("/ontology/all_jobs")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "table-action-link stop-job-action" in html
    assert "btn-small red darken-1 stop-job-btn" not in html


def test_create_app_imports_without_visualizer_dependency(monkeypatch):
    original_import = builtins.__import__

    def patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("taxonomy_ontology_accelerator"):
            raise ModuleNotFoundError("No module named 'taxonomy_ontology_accelerator'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "govuk_ai_accelerator_app", raising=False)
    monkeypatch.delitem(sys.modules, "taxonomy_ontology_accelerator", raising=False)
    monkeypatch.delitem(sys.modules, "taxonomy_ontology_accelerator.web", raising=False)
    monkeypatch.setattr(builtins, "__import__", patched_import)

    app_module = _app_module()
    client = Client(app_module.create_app(), Response)

    ontology_response = client.get("/ontology/")
    visualizer_response = client.get("/visualizer/")

    assert ontology_response.status_code == 200
    assert visualizer_response.status_code == 503
    assert "Visualizer is unavailable" in visualizer_response.get_data(as_text=True)


def test_serialize_job_datetime_marks_naive_datetimes_as_utc():
    app_module = _app_module()

    result = app_module._serialize_job_datetime(datetime(2026, 5, 11, 13, 18, 20))

    assert result == "2026-05-11T13:18:20Z"


def test_serialize_job_datetime_converts_aware_datetimes_to_utc():
    app_module = _app_module()
    bst = timezone(timedelta(hours=1))

    result = app_module._serialize_job_datetime(datetime(2026, 5, 11, 14, 18, 20, tzinfo=bst))

    assert result == "2026-05-11T13:18:20Z"


def test_list_jobs_returns_created_at_with_explicit_utc_marker(tmp_path):
    app_module = _app_module()
    flask_app = Flask(__name__)
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'jobs.db'}"
    app_module.db.init_app(flask_app)
    _, ontology_bp, _, _ = app_module.create_blueprints()
    flask_app.register_blueprint(ontology_bp)

    with flask_app.app_context():
        app_module.db.create_all()
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="created-at-job",
                status="done",
                domain="test-visa",
                created_at=datetime(2026, 5, 11, 13, 18, 20),
            )
        )
        app_module.db.session.commit()

    response = flask_app.test_client().get("/ontology/jobs")

    assert response.status_code == 200
    assert response.get_json()[0]["created_at"] == "2026-05-11T13:18:20Z"


def _jobs_test_app(tmp_path):
    app_module = _app_module()
    flask_app = Flask(__name__)
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'jobs.db'}"
    app_module.db.init_app(flask_app)
    _, ontology_bp, _, _ = app_module.create_blueprints()
    flask_app.register_blueprint(ontology_bp)
    with flask_app.app_context():
        app_module.db.drop_all()
        app_module.db.create_all()
    return app_module, flask_app


def test_stop_job_marks_running_job_failed_and_clears_lease(tmp_path):
    app_module, flask_app = _jobs_test_app(tmp_path)
    now = datetime.now(timezone.utc)

    with flask_app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="running-job",
                status="running",
                domain="test-visa",
                claimed_by="pod-a",
                claimed_at=now,
                heartbeat_at=now,
                last_progress_at=now,
                created_at=now,
            )
        )
        app_module.db.session.commit()

    response = flask_app.test_client().post("/ontology/jobs/running-job/stop")

    with flask_app.app_context():
        job = app_module.db.session.get(app_module.ProcessingJob, "running-job")

    assert response.status_code == 200
    assert response.get_json()["status"] == "failed"
    assert job.status == "failed"
    assert job.error_message == "Manually stopped from Jobs UI"
    assert job.claimed_by is None
    assert job.claimed_at is None
    assert job.heartbeat_at is None


def test_stop_job_rejects_completed_job(tmp_path):
    app_module, flask_app = _jobs_test_app(tmp_path)

    with flask_app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="completed-job",
                status="completed",
                domain="test-visa",
                job_runs="run-20260518-1",
                created_at=datetime.now(timezone.utc),
            )
        )
        app_module.db.session.commit()

    response = flask_app.test_client().post("/ontology/jobs/completed-job/stop")

    with flask_app.app_context():
        job = app_module.db.session.get(app_module.ProcessingJob, "completed-job")

    assert response.status_code == 409
    assert job.status == "completed"
    assert job.job_runs == "run-20260518-1"


def test_stop_job_returns_404_for_unknown_job(tmp_path):
    _, flask_app = _jobs_test_app(tmp_path)

    response = flask_app.test_client().post("/ontology/jobs/missing-job/stop")

    assert response.status_code == 404
