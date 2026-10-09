# TW Accelerator API Usage

This document records how the GOV.UK AI Accelerator app (`govuk-ai-accelerator`,
referred to here as **TW**) calls the `taxonomy_ontology_accelerator` Python
package. The package is installed into the same process as the Flask app; TW
does not call a separate Generator HTTP service.

The package is currently installed from the local
`lib/taxonomy_ontology_accelerator-2.0.12-py3-none-any.whl` wheel, declared in
[pyproject.toml](../../pyproject.toml) and copied into the container by [`Dockerfile`](../../Dockerfile).

## Integration overview

| TW surface                                                            | Package API                                                                                 | Purpose                                                                           |
|-----------------------------------------------------------------------|---------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [utils.py](../../scripts/pipeline/utils.py)                           | `OntologyConfig`, `OntologyConfigLoader`                                                    | Create the package's validated ontology configuration from submitted config data. |
| [ontology_generator.py](../../scripts/pipeline/ontology_generator.py) | `OntologyPipelineBuilder`                                                                   | Run ontology generation and write its artifacts.                                  |
| [ontology_generator.py](../../scripts/pipeline/ontology_generator.py) | `storage.cache.clear_caches`                                                                | Clear package runtime caches before each generation.                              |
| [ontology_harness.py](../../scripts/pipeline/ontology_harness.py)     | `build_ontology_metrics_from_turtle`, `RegressionReportContext`, `compare_ontology_metrics` | Extract metrics from baseline/candidate Turtle files and compare them.            |
| [govuk_ai_accelerator_app.py](../../govuk_ai_accelerator_app.py)      | `taxonomy_ontology_accelerator.web.app`                                                     | Mount the package visualizer under `/visualizer`.                                 |

## Ontology generation

The generation path is invoked by the background job manager:

1. A user submits JSON/YAML configuration and an optional prompt through
   `POST /ontology/submit` (`govuk_ai_accelerator_app.py`). TW stores these on a
   `ProcessingJob`; the task manager dispatches the job to
   `run_ontology_background_task`.
2. `run_ontology_pipeline` (`scripts/pipeline/ontology_generator.py`) calls
   `_clear_toa_runtime_caches`, then `load_config_for_domain`
   (`scripts/pipeline/utils.py`).
3. `load_config_for_domain` makes a TW `PipelineConfig` and calls
   `OntologyConfig(**config_data)` through `config_builder`. `PipelineConfig`
   extracts `domain_name` and the `path` values `input_path`, `output_dir`, and
   `prompt_path`. Path-based loading is not implemented in TW.
4. TW creates an `fsspec` filesystem from
   `ontology_config.filesystem.protocol` and constructs
   `OntologyPipelineBuilder` with:

   | Argument        | Value supplied by TW                                       |
   |-----------------|------------------------------------------------------------|
   | `domain`        | `pipeline_config.domain_name`                              |
   | `config`        | Validated package `OntologyConfig`                         |
   | `incremental`   | The pipeline function's boolean argument (default `False`) |
   | `input_path`    | `pipeline_config.input_path`                               |
   | `fs`            | Filesystem selected from the package config's protocol     |
   | `domain_prompt` | Prompt string supplied by the job (optional)               |

5. TW calls package builder methods in this order:

   | TW stage | Package method(s)                                                                                                |
   |----------|------------------------------------------------------------------------------------------------------------------|
   | Setup    | `setup_pipeline(input_path, output_dir, prompt_path)`; `load_existing()` if `pipeline.state.incremental` is true |
   | Extract  | `await extract_async()`                                                                                          |
   | Process  | `await deduplicate()`, `await build_relations()`, `await update_schema()`                                        |
   | Graph    | `await merge()` if incremental; then `validate()`, `save()`, `export()`                                          |
   | Finalize | `await finalize()` followed by `build()`                                                                         |

   The package's `finalize()` also handles merge when an existing graph is
   present, validation, saving, enabled OWL/RDF export, and finalization of
   package run artifacts. TW's explicit graph-stage calls precede this method,
   so validation/save/export are requested explicitly and then again through
   `finalize()` (and merge may also be requested both ways when incremental).
   This is part of the current call pattern and is worth reviewing when
   replacing or adapting the builder.

### Generation input and output boundary

**Inputs into the package** are the full submitted configuration mapping, the
domain and path values extracted by TW, the optional prompt text, the
incremental flag, and the selected filesystem. The config may originate from
the UI's default template, uploaded YAML, or submitted JSON. When a UI domain
is selected with S3 storage, TW sets `domain_name`, `path.input_path`, and
`path.output_dir` before queuing the job.

**Return value used by TW:** `pipeline.state.output_dir`, converted to a string.
TW uses it to persist `config.yaml`, derive the run ID, update job status, and
locate harness output. TW calls `pipeline.build()` but does not use the returned
`OntologyOutput` object. In the installed package, `build()` returns an
`OntologyOutput` with `ontology_schema`, `graph`, `metadata`, `errors`,
`schema_path`, and `graph_path`.

**Files used by TW after generation:** `schema.json`, `graph.json`, and
`ontology.ttl` are surfaced by the artifact browser and downloads. Other known
package artifacts surfaced or consumed by TW include `owl_ontology_metrics.csv`,
`bedrock_costs.csv`, `export_status.json`, `deduplication_summary.json`, and
`stdout.log`. The exact artifact set is controlled by the package configuration
and generator behavior.

## Ontology harness

The post-deployment harness uses the same `run_ontology_pipeline` generation
path, then compares the candidate Turtle output to an accepted baseline.

In `scripts/pipeline/ontology_harness.py`:

- `_build_ontology_metrics_from_turtle(turtle_content)` passes baseline and
  candidate Turtle text to the package's
  `build_ontology_metrics_from_turtle`. The package returns a
  `dict[str, float]` with keys `class_count`, `object_property_count`,
  `data_property_count`, `subclass_hierarchy_count`, `property_domain_count`,
  `property_range_count`, `disjointness_count`, `inverse_property_count`,
  `cardinality_restriction_count`, `equivalent_class_count`,
  `relationship_density`, `attribute_richness`, and
  `max_inheritance_depth`.
- `_compare_ontology_metrics(baseline_metrics, candidate_metrics, **metadata)`
  creates a package `RegressionReportContext` from the domain, deployment,
  baseline/candidate run IDs, output URIs, ontology URIs, and optional baseline
  promotion metadata. It passes the metric dictionaries, context, and any
  remaining keyword arguments to `compare_ontology_metrics`. The package
  returns a JSON-ready mapping with `passed`, `domain`, `deployment_version`,
  `baseline` and `candidate` metadata/metrics, per-metric `checks`, and
  `failed_metrics`.
- TW writes the returned JSON-ready report to `regression_report.json` and
  writes a summary (pass/fail, baseline run, deployment, failed metrics, report
  URI) into the candidate `owl_ontology_metrics.csv` row.

The harness therefore depends on both the package's metric names and report
shape, in addition to the generated `ontology.ttl` format.

## Visualizer

`govuk_ai_accelerator_app.py` imports `taxonomy_ontology_accelerator.web.app`
at application startup and mounts its `.app` ASGI application at
`/visualizer`. TW builds visualizer links from a job's domain and run ID. If
the package import is unavailable, TW mounts a small fallback that responds
with HTTP 503 rather than preventing the rest of the app from starting.

## Replacement compatibility checklist

A replacement package or adapter needs to preserve or deliberately replace
these boundaries:

- Configuration construction and validation from the submitted configuration
  mapping, including the filesystem protocol and the `path` settings.
- The pipeline builder operations and asynchronous/synchronous stage behavior
  expected by TW, plus access to `state.incremental` and `state.output_dir`.
- Generation outputs and artifact paths consumed by the job UI, downloads, and
  harness.
- Turtle metric extraction, metric keys, comparison context, and report fields
  used for harness decisions and summaries.
- The visualizer ASGI app, or an explicit decision to remove/replace that UI.
- Runtime cache clearing, or an explicit decision that the new package has no
  corresponding cache lifecycle.
