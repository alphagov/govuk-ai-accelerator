import json
from datetime import datetime, timezone

from flask import Flask

import govuk_ai_accelerator_app as app_module
from scripts.pipeline import ontology_harness


def _harness_test_app(tmp_path):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'harness-test.db'}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app_module.db.init_app(app)
    with app.app_context():
        app_module.db.drop_all()
        app_module.db.create_all()
    return app


def test_schedule_ontology_harness_enqueues_once_per_domain_and_deployment(
    tmp_path,
    monkeypatch,
):
    app = _harness_test_app(tmp_path)
    monkeypatch.setenv("ONTOLOGY_HARNESS_ENABLED", "true")
    monkeypatch.setenv("ONTOLOGY_HARNESS_DEPLOYMENT_ID", "v115")
    monkeypatch.setenv("S3_BUCKET_NAME", "test-bucket")
    monkeypatch.delenv("ONTOLOGY_HARNESS_DOMAIN", raising=False)
    monkeypatch.delenv("ONTOLOGY_HARNESS_BASELINE_OUTPUT_URI", raising=False)
    monkeypatch.delenv("ONTOLOGY_HARNESS_BASELINE_MANIFEST_URI", raising=False)
    monkeypatch.setattr(
        ontology_harness,
        "_load_harness_config",
        lambda settings: {
            "domain_name": "from-config",
            "filesystem": {"protocol": "s3"},
            "path": {},
        },
    )

    ontology_harness.schedule_ontology_harness(app)
    ontology_harness.schedule_ontology_harness(app)

    with app.app_context():
        jobs = app_module.db.session.query(app_module.ProcessingJob).all()

    assert len(jobs) == 1
    job = jobs[0]
    config_data = json.loads(job.config_data)
    assert job.id == "ontology-harness-baseline:v115"
    assert job.status == "pending"
    assert job.pipeline == "ontology-harness"
    assert job.domain == "ontology-harness-baseline"
    assert config_data["domain_name"] == "ontology-harness-baseline"
    assert config_data["path"]["input_path"] == (
        "s3://test-bucket/ontology-harness-baseline/input"
    )
    assert config_data["path"]["output_dir"] == "s3://test-bucket/ontology-harness-baseline"
    assert config_data["harness"]["deployment_id"] == "v115"
    assert "deployment_commit_sha" not in config_data["harness"]
    assert "deployment_version" not in config_data["harness"]
    assert config_data["harness"]["baseline_manifest_uri"] == (
        "s3://test-bucket/ontology-harness-baseline/baselines/accepted.json"
    )


def test_schedule_ontology_harness_skips_when_disabled_or_version_missing(
    tmp_path,
    monkeypatch,
):
    app = _harness_test_app(tmp_path)
    monkeypatch.delenv("ONTOLOGY_HARNESS_ENABLED", raising=False)
    monkeypatch.delenv("ONTOLOGY_HARNESS_DEPLOYMENT_ID", raising=False)

    ontology_harness.schedule_ontology_harness(app)

    monkeypatch.setenv("ONTOLOGY_HARNESS_ENABLED", "true")
    ontology_harness.schedule_ontology_harness(app)

    with app.app_context():
        jobs = app_module.db.session.query(app_module.ProcessingJob).all()

    assert jobs == []


def test_run_ontology_harness_writes_report_and_marks_failed_on_regression(
    tmp_path,
    monkeypatch,
):
    app = _harness_test_app(tmp_path)
    app_module._cached_app = app
    baseline_output = tmp_path / "ontology-harness-baseline" / "run-20260519-1" / "output"
    candidate_output = tmp_path / "ontology-harness-baseline" / "run-20260520-1" / "output"
    baseline_manifest = tmp_path / "ontology-harness-baseline" / "baselines" / "accepted.json"
    baseline_output.mkdir(parents=True)
    baseline_manifest.parent.mkdir(parents=True)
    (baseline_output / "ontology.ttl").write_text("baseline ontology", encoding="utf-8")
    baseline_manifest.write_text(
        json.dumps(
            {
                "baseline_run_id": "run-20260519-1",
                "baseline_output_uri": str(baseline_output),
                "promoted_at": "2026-05-20T14:00:00Z",
                "notes": "Accepted baseline after CSMD-339 metric changes",
            }
        ),
        encoding="utf-8",
    )

    async def fake_run_ontology_pipeline(config_data, domain_prompt, job_id):
        candidate_output.mkdir(parents=True)
        (candidate_output / "ontology.ttl").write_text("candidate ontology", encoding="utf-8")
        return str(candidate_output)

    def fake_build_metrics(turtle_content):
        if "baseline" in turtle_content:
            return {"property_domain_count": 10.0}
        return {"property_domain_count": 4.0}

    def fake_compare_metrics(baseline_metrics, candidate_metrics, **kwargs):
        return {
            "passed": False,
            "domain": kwargs["domain"],
            "deployment_version": kwargs["deployment_version"],
            "baseline": {
                "run_id": kwargs["baseline_run_id"],
                "output_uri": kwargs["baseline_output_uri"],
                "ontology_uri": kwargs["baseline_uri"],
                "promoted_at": kwargs["baseline_promoted_at"],
                "notes": kwargs["baseline_notes"],
                "metrics": baseline_metrics,
            },
            "candidate": {
                "run_id": kwargs["candidate_run_id"],
                "output_uri": kwargs["candidate_output_uri"],
                "ontology_uri": kwargs["candidate_uri"],
                "metrics": candidate_metrics,
            },
            "checks": [
                {
                    "metric": "property_domain_count",
                    "baseline_value": 10.0,
                    "candidate_value": 4.0,
                    "threshold": 8.0,
                    "passed": False,
                }
            ],
            "failed_metrics": ["property_domain_count"],
        }

    monkeypatch.setattr(ontology_harness, "run_ontology_pipeline", fake_run_ontology_pipeline)
    monkeypatch.setattr(
        ontology_harness,
        "_build_ontology_metrics_from_turtle",
        fake_build_metrics,
    )
    monkeypatch.setattr(
        ontology_harness,
        "_compare_ontology_metrics",
        fake_compare_metrics,
    )

    with app.app_context():
        app_module.db.session.add(
            app_module.ProcessingJob(
                id="ontology-harness-baseline:v1",
                status="running",
                pipeline="ontology-harness",
                domain="ontology-harness-baseline",
                claimed_by="pod-a",
                claimed_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            )
        )
        app_module.db.session.commit()

    result = ontology_harness.run_ontology_harness_background_task(
        {
            "domain_name": "ontology-harness-baseline",
            "harness": {
                "deployment_id": "v115",
                "baseline_manifest_uri": str(baseline_manifest),
            },
        },
        domain_prompt=None,
        job_id="ontology-harness-baseline:v1",
    )

    with app.app_context():
        job = app_module.db.session.get(
            app_module.ProcessingJob,
            "ontology-harness-baseline:v1",
        )
    report = json.loads((candidate_output / "regression_report.json").read_text())

    assert result is False
    assert report["passed"] is False
    assert report["deployment_version"] == "v115"
    assert report["baseline"]["run_id"] == "run-20260519-1"
    assert report["baseline"]["output_uri"] == str(baseline_output)
    assert report["baseline"]["promoted_at"] == "2026-05-20T14:00:00Z"
    assert report["baseline"]["notes"] == "Accepted baseline after CSMD-339 metric changes"
    assert report["candidate"]["run_id"] == "run-20260520-1"
    assert report["candidate"]["output_uri"] == str(candidate_output)
    assert report["checks"][0]["metric"] == "property_domain_count"
    assert job.status == "failed"
    assert job.job_runs == "run-20260520-1"
    assert job.error_message == "Ontology harness regression failed: property_domain_count"
    assert job.claimed_by is None


def test_load_baseline_manifest_requires_run_id_and_output_uri(tmp_path):
    manifest = tmp_path / "accepted.json"
    manifest.write_text('{"baseline_run_id": "run-20260519-1"}', encoding="utf-8")

    try:
        ontology_harness._load_baseline_manifest(str(manifest))
    except ValueError as exc:
        assert str(exc) == "Baseline manifest must include baseline_run_id and baseline_output_uri"
    else:
        raise AssertionError("Expected invalid baseline manifest to fail")
