import asyncio

from fsspec.implementations.memory import MemoryFileSystem

from scripts.pipeline.ontology_generator import _save_version_info
from scripts.pipeline.utils import PipelineConfig


def test_save_version_info_writes_to_resolved_run_root():
    fs = MemoryFileSystem()
    config = PipelineConfig(
        domain_name="visa",
        version={"number": "0.1.2", "notes": "test"},
        path={
            "input_path": "memory://ontology-runs/input",
            "output_dir": "memory://ontology-runs",
            "prompt_path": "memory://ontology-runs/prompts/prompt.txt",
        },
        llm={},
    )

    resolved_output_dir = "memory://ontology-runs/run_20260309_v0.1.2/visa/run-20260309-1/output"

    asyncio.run(_save_version_info(config, resolved_output_dir, fs))

    assert fs.exists("memory://ontology-runs/run_20260309_v0.1.2/visa/run-20260309-1/version.json")
    assert not fs.exists("memory://ontology-runs/run_20260309_v0.1.2/version.json")
