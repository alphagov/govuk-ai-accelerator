import logging
import sys
import types

from scripts.pipeline import ontology_generator as og
from scripts.pipeline import ontology_harness as oh
from scripts.ingestion import ingestion_pipeline as ing


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


def _fake_configs(_config):
    ontology_config = types.SimpleNamespace(filesystem=types.SimpleNamespace(protocol="file"))
    pipeline_config = types.SimpleNamespace(
        domain_name="visa", input_path="in", output_dir="out", prompt_path="p"
    )
    return ontology_config, pipeline_config


async def _async_noop(*a, **k):
    return None


def test_pipeline_logs_three_phase_per_step(monkeypatch, caplog):
    monkeypatch.setattr(og, "load_config_for_domain", lambda config: _fake_configs(config))
    monkeypatch.setattr(og.fsspec, "filesystem", lambda protocol: object())
    monkeypatch.setattr(og, "_save_version_info", _async_noop)
    monkeypatch.setattr(og, "_persist_config_yaml", lambda *a, **k: None)
    monkeypatch.setattr(og, "_finalize_job_status", lambda *a, **k: None)
    monkeypatch.setattr(og, "_mark_job_progress", lambda *a, **k: None)
    monkeypatch.setattr(og, "_raise_if_job_stopped", lambda *a, **k: None)
    monkeypatch.setattr(og, "_raise_if_superseded", lambda *a, **k: None)

    pipeline_builder = types.ModuleType("taxonomy_ontology_accelerator.ontology_engine.pipeline_builder")
    pipeline_builder.OntologyPipelineBuilder = lambda **kwargs: _FakePipeline()
    ontology_engine = types.ModuleType("taxonomy_ontology_accelerator.ontology_engine")
    ontology_engine.pipeline_builder = pipeline_builder
    taxonomy_root = types.ModuleType("taxonomy_ontology_accelerator")
    taxonomy_root.ontology_engine = ontology_engine
    monkeypatch.setitem(sys.modules, "taxonomy_ontology_accelerator", taxonomy_root)
    monkeypatch.setitem(sys.modules, "taxonomy_ontology_accelerator.ontology_engine", ontology_engine)
    monkeypatch.setitem(
        sys.modules, "taxonomy_ontology_accelerator.ontology_engine.pipeline_builder", pipeline_builder
    )

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
    assert any("Successfully set up ontology pipeline in" in m and "job=JID-1" in m for m in messages)
    assert any("Successfully processed ontology data in" in m and "job=JID-1" in m for m in messages)
    assert any("Successfully saved pipeline output in" in m and "job=JID-1" in m for m in messages)


def test_harness_failure_log_includes_job_and_domain(monkeypatch, caplog):
    def _boom(*args, **kwargs):
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
