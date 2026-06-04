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
    assert any("Successfully set up ontology pipeline in" in m and "job=JID-1" in m for m in messages)
    assert any("Successfully processed ontology data in" in m and "job=JID-1" in m for m in messages)
    assert any("Successfully saved pipeline output in" in m and "job=JID-1" in m for m in messages)
