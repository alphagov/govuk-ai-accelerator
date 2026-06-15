import builtins
import io
import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
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
    monkeypatch.setattr(app_module, "schedule_ontology_harness", lambda app: None)
    monkeypatch.setattr(app_module, "start_task_manager", lambda app: calls.append(app))

    app_module.create_flask_app()

    assert calls == []


def test_ontology_dashboard_includes_stop_job_action():
    response = _client().get("/ontology/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<th scope="col" id="actions-header">Actions</th>' in html
    assert "table-action-link stop-job-action" in html
    assert "Stop<span class=\"govuk-visually-hidden\"> job" in html
    assert "['pending', 'running'].includes(job.status.toLowerCase())" in html
    assert "job.status.toLowerCase() === 'stopped'" in html


def test_ontology_dashboard_describes_default_config_flow():
    response = _client().get("/ontology/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="file" name="file" accept=".yaml,.yml" style="display: none;"' in html
    assert "Please select a YAML configuration file." not in html
    assert "Configuration Panel" in html
    assert "domain prompt template" in html


def test_historical_jobs_uses_link_styled_stop_job_action():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "govuk-button govuk-button--warning review-row-action stop-job-action" in html
    assert "open-notes-action" in html
    assert "review-job-actions" not in html
    assert "btn-small red darken-1 stop-job-btn" not in html


def test_historical_jobs_labels_ontology_harness_pipeline_as_test():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "pipelineTagModifier(pipeline)" in html
    assert "if (pipeline === 'ontology-harness') return 'purple';" in html
    assert "if (pipeline === 'ontology-harness') return 'test';" in html
    assert 'data-badge-caption="ontology-harness"' not in html


def test_create_flask_app_schedules_ontology_harness_before_task_manager(monkeypatch):
    app_module = _app_module()
    calls = []

    monkeypatch.setenv("DISABLE_TASK_MANAGER", "false")
    monkeypatch.setattr(app_module, "schedule_ontology_harness", lambda app: calls.append("harness"))
    monkeypatch.setattr(app_module, "start_task_manager", lambda app: calls.append("task-manager"))
    app_module._cached_app = None

    app_module.create_flask_app()

    assert calls == ["harness", "task-manager"]


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


def test_list_jobs_includes_note_metadata_without_s3_calls(tmp_path, monkeypatch):
    app_module, flask_app = _jobs_test_app(tmp_path)
    monkeypatch.setattr(
        "boto3.client",
        lambda service_name: pytest.fail(f"unexpected {service_name} client"),
    )

    with flask_app.app_context():
        job = app_module.ProcessingJob(
            id="recent-with-notes",
            status="completed",
            pipeline="ontology",
            domain="visa",
            created_at=datetime(2026, 5, 11, 13, 18, 20, tzinfo=timezone.utc),
        )
        app_module.db.session.add(job)
        app_module.db.session.flush()
        app_module.db.session.add(
            app_module.ProcessingJobNote(
                job_id=job.id,
                text="A useful review note",
                created_at=datetime(2026, 5, 11, 14, 18, 20, tzinfo=timezone.utc),
            )
        )
        app_module.db.session.commit()

    response = flask_app.test_client().get("/ontology/jobs?limit=5")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload[0]["notes_count"] == 1
    assert payload[0]["latest_note"]["text"] == "A useful review note"


def test_review_jobs_endpoint_paginates_ontology_jobs_and_excludes_other_types(tmp_path):
    app_module, flask_app = _jobs_test_app(tmp_path)
    created_at = datetime(2026, 5, 11, 13, 0, tzinfo=timezone.utc)

    with flask_app.app_context():
        for index in range(12):
            job = app_module.ProcessingJob(
                id=f"ontology-{index:02d}",
                status="completed",
                pipeline="ontology",
                domain="visa",
                created_at=created_at + timedelta(minutes=index),
            )
            app_module.db.session.add(job)

        app_module.db.session.add(
            app_module.ProcessingJob(
                id="ingestion-job",
                status="completed",
                pipeline="ingestion",
                domain="visa",
                created_at=created_at + timedelta(minutes=20),
            )
        )
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="harness-job",
                status="completed",
                pipeline="ontology-harness",
                domain="ontology-harness-baseline",
                created_at=created_at + timedelta(minutes=21),
            )
        )
        app_module.db.session.flush()
        app_module.db.session.add_all(
            [
                app_module.ProcessingJobNote(
                    job_id="ontology-11",
                    text="first note",
                    created_at=created_at + timedelta(hours=1),
                ),
                app_module.ProcessingJobNote(
                    job_id="ontology-11",
                    text="latest note",
                    created_at=created_at + timedelta(hours=2),
                ),
            ]
        )
        app_module.db.session.commit()

    response = flask_app.test_client().get(
        "/ontology/jobs/review?type=ontology&page=1&per_page=10"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["pagination"] == {
        "page": 1,
        "per_page": 10,
        "total_items": 12,
        "total_pages": 2,
        "has_next": True,
        "has_previous": False,
    }
    assert len(payload["jobs"]) == 10
    assert payload["jobs"][0]["job_id"] == "ontology-11"
    assert payload["jobs"][0]["notes_count"] == 2
    assert payload["jobs"][0]["latest_note"]["text"] == "latest note"
    assert {job["pipeline"] for job in payload["jobs"]} == {"ontology"}


def test_review_jobs_endpoint_filters_harness_jobs_for_review_tests(tmp_path):
    app_module, flask_app = _jobs_test_app(tmp_path)

    with flask_app.app_context():
        app_module.db.session.add_all(
            [
                app_module.ProcessingJob(
                    id="ontology-job",
                    status="completed",
                    pipeline="ontology",
                    domain="visa",
                    created_at=datetime(2026, 5, 11, 13, 0, tzinfo=timezone.utc),
                ),
                app_module.ProcessingJob(
                    id="test-job",
                    status="failed",
                    pipeline="ontology-harness",
                    domain="ontology-harness-baseline",
                    created_at=datetime(2026, 5, 11, 14, 0, tzinfo=timezone.utc),
                ),
            ]
        )
        app_module.db.session.commit()

    response = flask_app.test_client().get("/ontology/jobs/review?type=test")

    assert response.status_code == 200
    payload = response.get_json()
    assert [job["job_id"] for job in payload["jobs"]] == ["test-job"]
    assert payload["jobs"][0]["pipeline"] == "ontology-harness"


def test_jobs_template_exposes_ontology_harness_report_link():
    template = Path(__file__).parents[1] / "templates" / "jobs.html"
    html = template.read_text(encoding="utf-8")

    assert "ontology-harness" in html
    assert "/artifacts" in html
    assert "renderArtifactRows" in html
    assert "download_url" in html
    assert "browse files" not in html


def test_source_config_template_uses_ui_selected_domain():
    template = Path(__file__).parents[1] / "static/assets/templates/config-template.yaml"
    template_text = template.read_text(encoding="utf-8")
    config = yaml.safe_load(template_text)

    assert "<domain>" not in template_text
    assert "domain_name" not in config
    assert "<path-to-input>" not in template_text
    assert "<path-to-output>" not in template_text


def test_root_config_template_omits_manual_domain_and_path_placeholders():
    template = Path(__file__).parents[1] / "config.yaml"
    template_text = template.read_text(encoding="utf-8")
    config = yaml.safe_load(template_text)

    assert "<domain>" not in template_text
    assert "<path-to-input>" not in template_text
    assert "<path-to-output>" not in template_text
    assert "domain_name" not in config
    assert config.get("path", {}) == {}


def test_submit_template_injects_selected_domain_paths(tmp_path):
    app_module, flask_app = _jobs_test_app(tmp_path)
    template = Path(__file__).parents[1] / "static/assets/templates/config-template.yaml"
    template_bytes = template.read_bytes()

    response = flask_app.test_client().post(
        "/ontology/submit",
        data={
            "domain": "visa",
            "file": (io.BytesIO(template_bytes), "config.yaml"),
        },
        content_type="multipart/form-data",
    )

    with flask_app.app_context():
        job = app_module.db.session.query(app_module.ProcessingJob).one()
        config_data = json.loads(job.config_data)

    assert response.status_code == 202
    assert job.domain == "visa"
    assert config_data["domain_name"] == "visa"
    assert config_data["path"]["input_path"] == (
        "s3://govuk-ai-accelerator-data-integration/visa/input"
    )
    assert config_data["path"]["output_dir"] == "s3://govuk-ai-accelerator-data-integration/visa"
    assert "input_path" not in config_data
    assert "output_dir" not in config_data


def test_submit_uses_default_config_and_prompt_when_files_are_omitted(tmp_path):
    app_module, flask_app = _jobs_test_app(tmp_path)

    response = flask_app.test_client().post(
        "/ontology/submit",
        data={"domain": "visa"},
    )

    with flask_app.app_context():
        job = app_module.db.session.query(app_module.ProcessingJob).one()
        config_data = json.loads(job.config_data)

    assert response.status_code == 202
    assert job.domain == "visa"
    assert job.domain_prompt == "#"
    assert config_data["domain_name"] == "visa"
    assert config_data["path"]["input_path"] == (
        "s3://govuk-ai-accelerator-data-integration/visa/input"
    )
    assert config_data["path"]["output_dir"] == "s3://govuk-ai-accelerator-data-integration/visa"
    assert config_data["version"]["number"] == "0.1.2"


def test_submit_uses_default_prompt_when_prompt_file_is_omitted(tmp_path):
    app_module, flask_app = _jobs_test_app(tmp_path)
    template = Path(__file__).parents[1] / "static/assets/templates/config-template.yaml"

    response = flask_app.test_client().post(
        "/ontology/submit",
        data={
            "domain": "visa",
            "file": (io.BytesIO(template.read_bytes()), "config.yaml"),
        },
        content_type="multipart/form-data",
    )

    with flask_app.app_context():
        job = app_module.db.session.query(app_module.ProcessingJob).one()

    assert response.status_code == 202
    assert job.domain_prompt == "#"


def test_submit_uses_uploaded_prompt_when_supplied(tmp_path):
    app_module, flask_app = _jobs_test_app(tmp_path)

    response = flask_app.test_client().post(
        "/ontology/submit",
        data={
            "domain": "visa",
            "text_file": (io.BytesIO(b"custom prompt"), "prompt.txt"),
        },
        content_type="multipart/form-data",
    )

    with flask_app.app_context():
        job = app_module.db.session.query(app_module.ProcessingJob).one()

    assert response.status_code == 202
    assert job.domain_prompt == "custom prompt"


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


def test_stop_job_marks_running_job_stopped_and_clears_lease(tmp_path):
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
    assert response.get_json()["status"] == "stopped"
    assert job.status == "stopped"
    assert job.error_message == "Manually stopped from Jobs UI"
    assert job.claimed_by is None
    assert job.claimed_at is None
    assert job.heartbeat_at is None


def test_completed_callback_does_not_overwrite_stopped_job(tmp_path):
    from scripts.pipeline import ontology_generator

    app_module, flask_app = _jobs_test_app(tmp_path)
    app_module._cached_app = flask_app

    with flask_app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="stopped-job",
                status="stopped",
                domain="test-visa",
                error_message="Manually stopped from Jobs UI",
                created_at=datetime.now(timezone.utc),
            )
        )
        app_module.db.session.commit()

    ontology_generator._update_job_status(
        "stopped-job",
        "completed",
        job_runs="run-20260521-1",
        clear_lease=True,
    )

    with flask_app.app_context():
        job = app_module.db.session.get(app_module.ProcessingJob, "stopped-job")

    assert job.status == "stopped"
    assert job.error_message == "Manually stopped from Jobs UI"
    assert job.job_runs is None


def test_ontology_task_keeps_stopped_job_stopped_when_stop_detected(tmp_path, monkeypatch):
    from scripts.pipeline import ontology_generator

    app_module, flask_app = _jobs_test_app(tmp_path)
    app_module._cached_app = flask_app

    with flask_app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="stopping-job",
                status="stopped",
                domain="test-visa",
                error_message="Manually stopped from Jobs UI",
                created_at=datetime.now(timezone.utc),
            )
        )
        app_module.db.session.commit()

    async def fake_run_ontology_pipeline(*_args, **_kwargs):
        raise ontology_generator.JobStoppedError("Job was manually stopped")

    monkeypatch.setattr(ontology_generator, "run_ontology_pipeline", fake_run_ontology_pipeline)

    result = ontology_generator.run_ontology_background_task(
        {"domain_name": "test-visa"},
        "prompt",
        "stopping-job",
    )

    with flask_app.app_context():
        job = app_module.db.session.get(app_module.ProcessingJob, "stopping-job")

    assert result is False
    assert job.status == "stopped"
    assert job.error_message == "Manually stopped from Jobs UI"


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


def test_job_notes_endpoints_use_database_notes(tmp_path):
    app_module, flask_app = _jobs_test_app(tmp_path)

    with flask_app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="notes-test-job",
                status="completed",
                domain="test-domain",
                job_runs="run-20260605-1",
                created_at=datetime.now(timezone.utc),
            )
        )
        app_module.db.session.commit()

    response = flask_app.test_client().post(
        "/ontology/jobs/notes-test-job/notes",
        json={"text": "This is a test note"},
    )

    assert response.status_code == 201
    created_note = response.get_json()
    assert created_note["text"] == "This is a test note"

    response = flask_app.test_client().get("/ontology/jobs/notes-test-job/notes")

    assert response.status_code == 200
    notes = response.get_json()
    assert [note["text"] for note in notes] == ["This is a test note"]

    response = flask_app.test_client().patch(
        f"/ontology/jobs/notes-test-job/notes/{created_note['id']}",
        json={"text": "Updated note"},
    )

    assert response.status_code == 200
    assert response.get_json()["text"] == "Updated note"

    response = flask_app.test_client().delete(
        f"/ontology/jobs/notes-test-job/notes/{created_note['id']}"
    )

    assert response.status_code == 204

    response = flask_app.test_client().get("/ontology/jobs/notes-test-job/notes")

    assert response.status_code == 200
    assert response.get_json() == []


def test_job_notes_get_imports_legacy_s3_notes_once(tmp_path, monkeypatch):
    app_module, flask_app = _jobs_test_app(tmp_path)
    notes_payload = [
        {"id": "1", "text": "Imported note", "timestamp": "2026-06-05T12:00:00Z"}
    ]

    with flask_app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="legacy-notes-job",
                status="completed",
                domain="test-domain",
                job_runs="run-20260605-1",
                created_at=datetime.now(timezone.utc),
            )
        )
        app_module.db.session.commit()

    mock_s3_client = MagicMock()
    mock_body = MagicMock()
    mock_body.read.return_value = json.dumps(notes_payload).encode("utf-8")
    mock_s3_client.get_object.return_value = {"Body": mock_body}
    monkeypatch.setattr("boto3.client", lambda service_name: mock_s3_client)

    response = flask_app.test_client().get("/ontology/jobs/legacy-notes-job/notes")

    assert response.status_code == 200
    assert [note["text"] for note in response.get_json()] == ["Imported note"]
    mock_s3_client.get_object.assert_called_once_with(
        Bucket="govuk-ai-accelerator-data-integration",
        Key="test-domain/run-20260605-1/notes.json"
    )

    mock_s3_client.get_object.reset_mock()
    response = flask_app.test_client().get("/ontology/jobs/legacy-notes-job/notes")

    assert response.status_code == 200
    assert [note["text"] for note in response.get_json()] == ["Imported note"]
    mock_s3_client.get_object.assert_not_called()


def test_job_artifacts_endpoint_groups_downloadable_files_and_folders(tmp_path, monkeypatch):
    app_module, flask_app = _jobs_test_app(tmp_path)

    with flask_app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="artifact-job",
                status="completed",
                pipeline="ontology",
                domain="visa",
                job_runs="run-20260605-1",
                config_data=json.dumps(
                    {
                        "domain_name": "visa",
                        "path": {"input_path": "s3://test-bucket/visa/input"},
                    }
                ),
                domain_prompt="review prompt",
                created_at=datetime.now(timezone.utc),
            )
        )
        app_module.db.session.commit()

    class FakePaginator:
        def paginate(self, **kwargs):
            prefix = kwargs["Prefix"]
            if prefix == "visa/run-20260605-1/":
                return [
                    {
                        "Contents": [
                            {"Key": "visa/run-20260605-1/config.yaml", "Size": 9},
                            {"Key": "visa/run-20260605-1/output/graph.json", "Size": 10},
                            {"Key": "visa/run-20260605-1/output/ontology.ttl", "Size": 11},
                            {"Key": "visa/run-20260605-1/output/schema.json", "Size": 12},
                            {"Key": "visa/run-20260605-1/output/bedrock_costs.csv", "Size": 13},
                            {"Key": "visa/run-20260605-1/output/deduplication.jsonl", "Size": 14},
                            {"Key": "visa/run-20260605-1/output/checkpoints/state.json", "Size": 15},
                            {"Key": "visa/run-20260605-1/output/regression_report.json", "Size": 16},
                        ]
                    }
                ]
            if prefix == "visa/input/":
                return [{"Contents": [{"Key": "visa/input/source.md", "Size": 17}]}]
            return []

    mock_s3_client = MagicMock()
    mock_s3_client.get_paginator.return_value = FakePaginator()
    monkeypatch.setenv("S3_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr("boto3.client", lambda service_name: mock_s3_client)

    response = flask_app.test_client().get("/ontology/jobs/artifact-job/artifacts")

    assert response.status_code == 200
    groups = response.get_json()["groups"]
    ontology_names = {artifact["name"] for artifact in groups["ontology_files"]}
    intermediary_names = {artifact["name"] for artifact in groups["intermediary_files"]}
    report_names = {artifact["name"] for artifact in groups["reports"]}
    assert {"graph.json", "ontology.ttl", "schema.json"} <= ontology_names
    assert {"config.yaml", "prompts.txt", "input", "output"} <= intermediary_names
    assert "Submitted config.yaml" not in intermediary_names
    assert "Prompt used" not in intermediary_names
    assert "bedrock_costs.csv" not in intermediary_names
    assert "deduplication.jsonl" not in intermediary_names
    assert "checkpoints" not in intermediary_names
    assert "input/source.md" not in intermediary_names
    assert report_names == {"regression_report.json"}
    assert all("view" not in artifact for group in groups.values() for artifact in group)
    assert all(artifact["action"] == "download" for group in groups.values() for artifact in group)

    graph_artifact = next(
        artifact
        for artifact in groups["ontology_files"]
        if artifact["name"] == "graph.json"
    )
    ontology_artifact = next(
        artifact
        for artifact in groups["ontology_files"]
        if artifact["name"] == "ontology.ttl"
    )
    assert graph_artifact["visualize_url"] == "/visualizer/?run=visa/run-20260605-1"
    assert graph_artifact["download_label"] == "Download"
    assert ontology_artifact["download_label"] == "Download ontology"


def test_job_artifacts_endpoint_includes_local_input_and_output_downloads(tmp_path):
    app_module, flask_app = _jobs_test_app(tmp_path)
    input_dir = tmp_path / "run" / "input"
    output_dir = tmp_path / "run" / "output"
    nested_input_dir = input_dir / "guidance"
    nested_input_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    (input_dir / "source.md").write_text("source", encoding="utf-8")
    (nested_input_dir / "nested.md").write_text("nested", encoding="utf-8")
    (output_dir / "graph.json").write_text("{}", encoding="utf-8")
    (output_dir / "bedrock_costs.csv").write_text("cost", encoding="utf-8")

    with flask_app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="local-artifact-job",
                status="completed",
                pipeline="ontology",
                domain="visa",
                config_data=json.dumps(
                    {
                        "domain_name": "visa",
                        "path": {
                            "input_path": input_dir.as_uri(),
                            "output_dir": output_dir.as_uri(),
                        },
                    }
                ),
                domain_prompt="review prompt",
                created_at=datetime.now(timezone.utc),
            )
        )
        app_module.db.session.commit()

    response = flask_app.test_client().get("/ontology/jobs/local-artifact-job/artifacts")

    assert response.status_code == 200
    groups = response.get_json()["groups"]
    ontology_names = {artifact["name"] for artifact in groups["ontology_files"]}
    intermediary_names = {artifact["name"] for artifact in groups["intermediary_files"]}
    assert "graph.json" in ontology_names
    assert {"input", "output"} <= intermediary_names
    assert "input/source.md" not in intermediary_names
    assert "input/guidance" not in intermediary_names
    assert "bedrock_costs.csv" not in intermediary_names

    input_artifact = next(
        artifact
        for artifact in groups["intermediary_files"]
        if artifact["name"] == "input"
    )
    download_response = flask_app.test_client().get(input_artifact["download_url"])

    assert download_response.status_code == 200
    assert download_response.mimetype == "application/zip"
    assert "attachment; filename=input.zip" in download_response.headers["Content-Disposition"]


def test_virtual_and_folder_download_routes(tmp_path, monkeypatch):
    app_module, flask_app = _jobs_test_app(tmp_path)

    with flask_app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="download-job",
                status="completed",
                domain="visa",
                job_runs="run-20260605-1",
                config_data=json.dumps({"domain_name": "visa"}),
                domain_prompt="prompt text",
                created_at=datetime.now(timezone.utc),
            )
        )
        app_module.db.session.commit()

    config_response = flask_app.test_client().get(
        "/ontology/jobs/download-job/downloads/config.yaml"
    )
    prompt_response = flask_app.test_client().get(
        "/ontology/jobs/download-job/downloads/prompts.txt"
    )

    assert config_response.status_code == 200
    assert "domain_name: visa" in config_response.get_data(as_text=True)
    assert "attachment; filename=config.yaml" in config_response.headers["Content-Disposition"]
    assert prompt_response.status_code == 200
    assert prompt_response.get_data(as_text=True) == "prompt text"
    assert "attachment; filename=prompts.txt" in prompt_response.headers["Content-Disposition"]

    class FakePaginator:
        def paginate(self, **kwargs):
            assert kwargs["Prefix"] == "visa/run-20260605-1/output/checkpoints/"
            return [
                {
                    "Contents": [
                        {
                            "Key": "visa/run-20260605-1/output/checkpoints/state.json",
                            "Size": 12,
                        }
                    ]
                }
            ]

    mock_s3_client = MagicMock()
    mock_s3_client.get_paginator.return_value = FakePaginator()
    mock_body = MagicMock()
    mock_body.read.return_value = b'{"state": true}'
    mock_s3_client.get_object.return_value = {"Body": mock_body}
    monkeypatch.setattr("boto3.client", lambda service_name: mock_s3_client)

    zip_response = flask_app.test_client().get(
        "/ontology/jobs/download-job/downloads/folder"
        "?bucket=govuk-ai-accelerator-data-integration"
        "&prefix=visa/run-20260605-1/output/checkpoints/"
    )

    import zipfile

    archive = zipfile.ZipFile(io.BytesIO(zip_response.data))
    assert zip_response.status_code == 200
    assert archive.namelist() == ["state.json"]
    assert archive.read("state.json") == b'{"state": true}'


def test_govuk_frontend_assets_are_served():
    response = _client().get("/assets/images/favicon.ico")

    assert response.status_code == 200


def test_govuk_frontend_assets_are_cached_immutably():
    response = _client().get("/assets/fonts/light-94a07e06a1-v2.woff2")

    assert response.status_code == 200
    cache_control = response.headers["Cache-Control"]
    assert "public" in cache_control
    assert "max-age=31536000" in cache_control
    assert "immutable" in cache_control
    assert "no-cache" not in cache_control


def test_header_uses_govuk_service_navigation():
    response = _client().get("/ontology/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'class="govuk-header"' in html
    assert "govuk-service-navigation" in html
    assert "vendor/govuk-frontend/govuk-frontend.min.css" in html


def test_header_navigation_links_map_labels_to_paths():
    response = _client().get("/ontology/domains")
    html = response.get_data(as_text=True)

    assert '<a class="govuk-service-navigation__link" href="/ontology"' in html
    assert "Home" in html
    assert '<a class="govuk-service-navigation__link" href="/ontology/review-ontologies"' in html
    assert "Review Ontologies" in html
    assert "Create Domains" in html
    assert '<a class="govuk-service-navigation__link" href="/ontology/review-tests"' in html
    assert "Review Tests" in html
    assert html.index("Create Domains") < html.index("Review Tests")
    assert html.index("Review Tests") < html.index("File Explorer")
    assert (
        '<a class="govuk-service-navigation__link" '
        'href="/viewer/bucket/govuk-ai-accelerator-data-integration"' in html
    )
    assert "File Explorer" in html


def test_header_marks_home_active_on_dashboard():
    response = _client().get("/ontology/")
    html = response.get_data(as_text=True)

    assert '<a class="govuk-service-navigation__link" href="/ontology" aria-current="page">' in html
    assert '<strong class="govuk-service-navigation__active-fallback">Home</strong>' in html


def test_header_marks_create_domains_active_on_domains():
    response = _client().get("/ontology/domains")
    html = response.get_data(as_text=True)

    assert (
        '<a class="govuk-service-navigation__link" href="/ontology/domains" '
        'aria-current="page">' in html
    )
    assert (
        '<strong class="govuk-service-navigation__active-fallback">Create Domains</strong>'
        in html
    )


def test_header_marks_review_ontologies_active_on_all_jobs():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert (
        '<a class="govuk-service-navigation__link" href="/ontology/review-ontologies" '
        'aria-current="page">' in html
    )
    assert (
        '<strong class="govuk-service-navigation__active-fallback">Review Ontologies</strong>'
        in html
    )


def test_header_marks_review_tests_active_on_review_tests():
    response = _client().get("/ontology/review-tests")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert (
        '<a class="govuk-service-navigation__link" href="/ontology/review-tests" '
        'aria-current="page">' in html
    )
    assert '<strong class="govuk-service-navigation__active-fallback">Review Tests</strong>' in html


def test_jobs_page_renders_review_table_headings():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<h2>Review Ontologies</h2>" in html
    assert '<table class="review-jobs-table" id="jobs-table">' in html
    for heading in ("Ontology", "Domain", "Created At", "Status", "Type", "Actions"):
        assert f"<span>{heading}</span>" in html
    for sort_key in ("ontology", "domain", "created_at", "status", "type"):
        assert f'data-sort-key="{sort_key}"' in html
    assert '<th scope="col" aria-sort="descending">' in html
    assert "data-sort-icon" not in html
    assert "sort-icon-active" not in html
    assert "sort-icon-inactive" not in html
    assert "↕" not in html
    assert "▲" not in html
    assert "▼" not in html


def test_review_tests_page_renders_test_title_and_type():
    response = _client().get("/ontology/review-tests")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<h2>Review Tests</h2>" in html
    assert 'const REVIEW_JOB_TYPE = "test";' in html
    assert 'const REVIEW_PAGE_TITLE = "Review Tests";' in html


def test_review_ontologies_page_uses_requested_subtitle():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert (
        "View your available ontologies below. Click any row to see more information about it."
        in html
    )


def test_review_ontologies_page_uses_paginated_review_api():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'const REVIEW_JOB_TYPE = "ontology";' in html
    assert "/ontology/jobs/review" in html
    assert "renderPagination" in html
    assert "currentPage = 1" in html
    assert "perPage = 10" in html


def test_jobs_page_wires_sort_controls_to_table_renderer():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "let sortKey = 'created_at';" in html
    assert "let sortDirection = 'desc';" in html
    assert "url.searchParams.set('sort', sortKey);" in html
    assert "url.searchParams.set('direction', sortDirection);" in html
    assert "function renderCurrentJobs()" in html
    assert "function updateSortIndicators()" in html
    assert "document.querySelectorAll('.review-sort-button')" in html
    assert "fetchReviewJobs();" in html


def test_jobs_page_prevents_mouse_click_selection_on_sort_headers():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "user-select: none;" in html
    assert "-webkit-tap-highlight-color: transparent;" in html
    assert ".review-sort-button:focus," in html
    assert "background: transparent !important;" in html
    assert ".review-sort-button:focus:not(:focus-visible)" in html


def test_jobs_page_removes_refresh_icon_from_review_header():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="refresh-jobs-btn"' not in html
    assert "Refresh jobs" not in html
    assert "refreshBtn" not in html


def test_jobs_page_renders_expanded_review_context_sections():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Ontology Files" in html
    assert "Reports" in html
    assert "Notes" in html
    assert "renderArtifactSection('Reports', groups.reports)" in html
    assert "renderInlineNotes(job, state.notes || [], state.editingNoteId)" in html
    assert "renderJobActions" not in html
    assert "renderStopAction" not in html


def test_jobs_page_uses_selected_job_artifact_api_and_download_only_rows():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "/artifacts" in html
    assert "download_url" in html
    assert "renderArtifactRows" in html
    assert "renderArtifactActions" in html
    assert "Visualise graph" in html
    assert "artifact.download_label" in html
    assert "review-artifact-actions" in html
    assert ">download</span>" not in html
    assert "visualiserLink" not in html
    assert "browse files" not in html
    assert "renderArtifactLink('Graph', visualiserLink, 'view')" not in html


def test_jobs_page_uses_govuk_pagination_markup_without_custom_button_tiles():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'class="govuk-pagination review-pagination"' in html
    assert "govuk-pagination__list" in html
    assert "govuk-pagination__prev" in html
    assert "govuk-pagination__next" in html
    assert "govuk-pagination__item--current" in html
    assert "review-pagination__item" not in html


def test_jobs_page_uses_inline_notes_without_per_row_sync_or_native_note_prompts():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "renderInlineNotes" in html
    assert "syncNotesFromS3(job.job_id)" not in html
    assert "Edit note text:" not in html
    assert "Are you sure you want to delete this note?" not in html
    assert "localStorage.setItem('job-notes-'" not in html


def test_jobs_page_orders_detail_menu_by_artifact_context():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert html.index("renderDetailTab('ontology-files', 'Ontology Files')") < html.index(
        "renderDetailTab('intermediary-files', 'Intermediary Files')"
    )
    assert html.index("renderDetailTab('intermediary-files', 'Intermediary Files')") < html.index(
        "renderDetailTab('reports', 'Reports')"
    )
    assert html.index("renderDetailTab('reports', 'Reports')") < html.index(
        "renderDetailTab('notes', 'Notes')"
    )


def test_jobs_page_uses_gds_tags_and_notes_modal_controls():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "govuk-tag review-tag" in html
    assert "if (status === 'pending') return 'yellow';" in html
    assert "return 'yellow';" in html
    assert "review-add-note-button add-inline-note-action" in html
    assert 'class="govuk-textarea review-note-textarea"' in html
    assert 'class="govuk-label govuk-label--s"' in html
    assert "review-note-button" not in html
    assert "chat_bubble_outline" not in html


def test_jobs_page_styles_note_actions_as_compact_icon_buttons():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "width: 32px;" in html
    assert "height: 32px;" in html
    assert "border: 1px solid #b1b4b6;" in html
    assert "background: #ffffff;" in html
    assert "line-height: 1;" in html


def test_left_sidebar_is_removed():
    response = _client().get("/ontology/")
    html = response.get_data(as_text=True)

    assert 'class="sidebar"' not in html
    assert '<aside' not in html


def test_service_navigation_neutralises_materialize_nav_styling():
    response = _client().get("/ontology/")
    html = response.get_data(as_text=True)

    assert ".govuk-service-navigation__wrapper {" in html
    assert "background-color: transparent;" in html
    assert ".govuk-service-navigation__link {" in html
    assert "font-size: inherit;" in html


def test_service_navigation_uses_rebranded_styling():
    response = _client().get("/ontology/")
    html = response.get_data(as_text=True)

    assert 'class="govuk-template--rebranded"' in html


def test_header_matches_graph_tools_brand_layout():
    response = _client().get("/ontology/")
    html = response.get_data(as_text=True)

    assert '<svg class="govuk-header__logotype"' in html
    assert 'height="28" width="150"' in html
    assert "<h1>Ontology Generator</h1>" in html
    assert 'class="govuk-header__content"' not in html
    assert html.index('<section aria-label="Service information"') < html.index("</header>")


def test_header_uses_graph_tools_brand_row_styling():
    response = _client().get("/ontology/")
    html = response.get_data(as_text=True)

    assert ".govuk-header > .govuk-width-container {" in html
    assert "padding-top: 14px;" in html
    assert "padding-bottom: 14px;" in html
    assert "align-items: flex-end;" in html
    assert "gap: 24px;" in html
    assert ".govuk-header__logo {" in html
    assert "gap: 16px;" in html
    assert ".govuk-header__logotype {" in html
    assert "width: 150px;" in html
    assert "height: 28px;" in html
    assert "padding-right: 16px;" in html
    assert "border-right: 1px solid rgba(255, 255, 255, 0.4);" in html
    assert ".govuk-header h1 {" in html
    assert "font-size: 24px;" in html
    assert "line-height: 1.1;" in html
    assert "letter-spacing: -0.01em;" in html
    assert "body.govuk-template--rebranded .govuk-header {" in html
    assert "body.govuk-template--rebranded .govuk-header__logo {" in html
    assert "body.govuk-template--rebranded .govuk-header__logotype {" in html
    assert ".govuk-header .govuk-service-navigation {" in html
    assert "font-size: 19px;" in html
    assert ".govuk-header .govuk-service-navigation__item {" in html
    assert ".govuk-header .govuk-service-navigation__link {" in html
    assert "display: inline;" in html
    assert "margin-right: auto;" in html


def test_header_preloads_govuk_fonts_to_avoid_navigation_font_swap():
    response = _client().get("/ontology/")
    html = response.get_data(as_text=True)

    assert 'rel="preload"' in html
    assert 'href="/assets/fonts/light-94a07e06a1-v2.woff2"' in html
    assert 'href="/assets/fonts/bold-b542beb274-v2.woff2"' in html
    assert 'as="font"' in html
    assert 'type="font/woff2"' in html


def test_header_resets_inner_container_border_that_causes_uneven_blue_height():
    response = _client().get("/ontology/")
    html = response.get_data(as_text=True)

    assert ".govuk-header__container {" in html
    assert "margin-bottom: 0;" in html
    assert "border-bottom: 0;" in html


def test_active_service_navigation_link_does_not_add_text_underline_to_active_bar():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert ".govuk-service-navigation__item--active .govuk-service-navigation__link" in html
    assert "text-decoration: none;" in html


def test_old_all_jobs_url_redirects_to_review_ontologies():
    response = _client().get("/ontology/all_jobs")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/ontology/review-ontologies")


def test_review_ontologies_page_uses_service_navigation_width():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<div class="review-jobs-page govuk-width-container">' in html
    assert "max-width: none;" not in html


def test_review_ontologies_page_uses_white_background():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "body {" in html
    assert "body.govuk-template--rebranded {" in html
    assert "background-color: #ffffff;" in html
    assert ".review-jobs-page {" in html
    assert "background: #ffffff;" in html


def test_review_ontologies_actions_column_has_room_for_actions():
    response = _client().get("/ontology/review-ontologies")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert ".review-jobs-table th:nth-child(6)" in html
    assert "width: 14%;" in html
    assert "min-width: 120px;" in html
