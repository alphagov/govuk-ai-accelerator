<!-- markdownlint-disable MD013 -->

# Ontology Generator Metrics Run Book

This run book helps you understand the metrics produced by the GOV.UK Ontology
Generator and decide what to do next when a run passes, fails, or looks
surprising.

It is written for a mixed audience. You do not need to know the codebase to use
the main guidance sections. The technical details are at the end for people who
need to investigate further.

## Start Here

The metrics are there to answer four practical questions:

1. Did the ontology run complete and produce the expected files?
2. Does the new ontology have a similar structure to the accepted baseline?
3. If something changed, which part of the ontology changed?
4. Is the change expected, or does someone need to investigate?

The metrics are useful signals, not a final quality score. They can tell you
that the generated ontology is smaller, flatter, less connected, more expensive,
or missing expected files. They cannot prove that the ontology is semantically
correct, complete, or useful for a specific policy/content task.

## Which Question Are You Trying To Answer?

| Question | Start with | Then check |
| --- | --- | --- |
| Did an ordinary ontology run complete? | **Review Ontologies** in the Ontology Generator web app | `ontology.ttl`, `schema.json`, `graph.json`, and `owl_ontology_metrics.csv` |
| Did the post-deployment harness pass? | **Review Tests** in the Ontology Generator web app | `Harness Result` and `regression_report.json` |
| Why did the harness fail? | `regression_report.json` | Failed metrics, baseline values, candidate values, and the generated ontology files |
| Did costs or token usage look unusual? | `bedrock_costs.csv` | Input/output tokens, model ID, run start/end time, and error fields |
| Did export fail or metrics go missing? | `export_status.json` | Export status, output path, timing fields, and `stdout.log` |
| Did deduplication change the output shape? | `deduplication_summary.json` | Entity counts before/after deduplication and merge counts |
| Should a new baseline be promoted? | Generated ontology files first, metrics second | Baseline manifest, candidate outputs, and written notes explaining the decision |

## Where To Find Metrics

Use the Ontology Generator web app first.

- **Review Ontologies** shows ordinary ontology runs.
- **Review Tests** shows ontology harness test runs.
- Open a job row to find downloads for generated files, reports, configuration,
  prompts, and logs.

The most important files are:

| File | What it is for |
| --- | --- |
| `owl_ontology_metrics.csv` | Main structural metrics for generated ontologies. |
| `regression_report.json` | Harness report comparing a candidate run against the accepted baseline. |
| `ontology.ttl` | Generated ontology in Turtle format. Use this when you need to inspect the ontology itself. |
| `schema.json` | Entity and relationship type definitions. |
| `graph.json` | Generated graph structure. |
| `bedrock_costs.csv` | Token usage and estimated Bedrock costs. |
| `export_status.json` | OWL export status and timing information. |
| `deduplication_summary.json` | Summary of how many entities were merged during deduplication. |
| `stdout.log` | Detailed run log. Use this when a run failed or an artifact is missing. |

## Quick Decisions

### If Metrics Pass

Recommended action:

1. Confirm the job status is `completed`.
2. Download the main artifacts if the run is part of a release or handover
   decision.
3. Spot-check `ontology.ttl`, `schema.json`, and `graph.json`.
4. Keep the run as evidence.
5. Do not promote a new baseline unless this run is intentionally becoming the
   new comparison point.

### If The Harness Fails

Recommended action:

1. Open the harness job in **Review Tests**.
2. Download `regression_report.json`.
3. Look at `failed_metrics`.
4. Compare the baseline value and candidate value for each failed metric.
5. Download the baseline and candidate `ontology.ttl` files if you need to
   inspect the ontology change directly.
6. Check whether the failure matches an intentional change to the prompt,
   config, model, schema, or export behaviour.
7. If the failure is unexpected, ask the relevant maintainer to fix the
   Generator or Workflow change and rerun.
8. If the failure is expected and acceptable, consider promoting a new baseline.

Do not disable the harness or change thresholds just to make a failed run pass.
If the old baseline no longer applies, record why.

### If Metrics Are Missing

Recommended action:

1. Confirm that `ontology.ttl` exists. The main metrics CSV is written during
   OWL/RDF export.
2. Check `export_status.json`.
3. Check `stdout.log` and application logs.
4. Confirm the run wrote to the expected domain and run folder.
5. Confirm the app can read the S3 bucket or local path.
6. Rerun the ontology job after fixing the export or storage issue.

### If Costs Look Wrong

Recommended action:

1. Open `bedrock_costs.csv`.
2. Check `model_id`, `input_tokens`, `output_tokens`, and
   `estimated_cost_usd`.
3. If costs are much higher than expected, check input size, prompt changes,
   retries, and model choice.
4. If costs are near zero, check whether the run skipped LLM calls, failed
   early, or did not process the expected input.

## What The Main Metrics Mean

These metrics describe the shape of the generated ontology. They are most useful
when compared with another run for the same domain.

| Metric | Plain-English meaning | When to pay attention |
| --- | --- | --- |
| `Class Count` | How many classes or concept types are in the ontology. | A sharp drop can mean concepts were lost. A sharp rise can mean over-extraction or schema growth. |
| `Object Properties Count` | How many relationship types connect classes or entities. | Too few can mean weak relationship extraction. Too many can mean noisy relationship vocabulary. |
| `Data Properties Count` | How many attribute types exist, such as literal fields or values. | A drop can mean attributes were lost. A rise can mean richer extraction or over-specific properties. |
| `Subclass Hierarchies` | How many parent-child class links exist. | Low values can mean the ontology is too flat. |
| `Property Domains` | How many properties define what type they start from. | A drop can mean relationships are less constrained. |
| `Property Ranges` | How many properties define what type they point to. | A drop can mean relationship targets are less well specified. |
| `Disjointness` | How many declarations say two classes/properties should not overlap. | Usually low or zero. Inspect any unexpected change. |
| `Inverse Properties` | How many relationships have explicit reverse relationships. | Useful when reverse meaning matters. Inspect sudden changes. |
| `Cardinality Restriction` | How many min/max count restrictions exist. | Usually low or zero unless the ontology deliberately models strict OWL constraints. |
| `Equivalent Classes` | How many declarations say classes are equivalent. | Usually low or zero. A rise may be deliberate modelling or accidental duplication. |
| `Relationships Density` | Object properties divided by class count. | Shows how relationship-heavy the ontology is. Compare with the baseline. |
| `Attribute Richness` | Data properties divided by class count. | Shows how attribute-heavy the ontology is. Compare with the baseline. |
| `Max Inheritance Depth` | The deepest parent-child class chain. | Very low can mean a flat ontology. Very high can mean over-nesting. |

If you are unsure what a metric change means, inspect the generated ontology
files rather than relying on the number alone.

## How The Harness Result Works

The harness is a post-deployment check. It runs the Generator against a known
baseline domain and compares the candidate run with an accepted baseline run.

The harness result is written back into `owl_ontology_metrics.csv` using these
columns:

| Column | Meaning |
| --- | --- |
| `Harness Result` | `PASS` or `FAIL`. |
| `Harness Baseline Run ID` | The accepted run used for comparison. |
| `Harness Deployment ID` | The deployment or Generator revision being checked. |
| `Harness Failed Metrics` | The metrics that failed the comparison. |
| `Harness Report URI` | Where to download the full report. |

The harness checks for large drops in key structural metrics. Current default
checks are:

| Harness metric | Related CSV metric | Current threshold |
| --- | --- | --- |
| `subclass_hierarchy_count` | `Subclass Hierarchies` | Candidate must be at least 80% of baseline. |
| `property_domain_count` | `Property Domains` | Candidate must be at least 80% of baseline. |
| `property_range_count` | `Property Ranges` | Candidate must be at least 80% of baseline. |
| `relationship_density` | `Relationships Density` | Candidate must be at least 80% of baseline. |
| `attribute_richness` | `Attribute Richness` | Candidate must be at least 80% of baseline. |
| `max_inheritance_depth` | `Max Inheritance Depth` | Candidate may drop by at most 1. |

A failed harness does not automatically mean the candidate is bad. It means the
candidate changed enough that someone should review it.

## Baseline Promotion

Promoting a baseline means telling future harness runs to compare against a new
accepted run.

Only promote a new baseline when the team has reviewed the generated ontology
and agrees the new output shape is acceptable. Do not promote a baseline just to
make a failed deployment green.

Recommended action before promotion:

1. Review `ontology.ttl`, `schema.json`, and `graph.json`.
2. Compare the candidate run against the previous baseline.
3. Confirm the change is expected and acceptable.
4. Record the reason in `baselines/accepted.json`.
5. Point `baseline_run_id` and `baseline_output_uri` at an immutable run.
6. Do not move, rewrite, or delete the run folder after promotion.
7. Rerun or wait for the next harness run to confirm the new baseline works.

Example baseline manifest:

```json
{
  "baseline_run_id": "run-20260520-1",
  "baseline_output_uri": "s3://govuk-ai-accelerator-data-integration/ontology-harness-baseline/run-20260520-1/output",
  "promoted_at": "2026-05-20T14:00:00Z",
  "notes": "Accepted baseline after metric changes"
}
```

## Common Scenarios

| Scenario | What to check next |
| --- | --- |
| Harness failed on `property_domain_count` or `property_range_count` | Check whether relationship/property export lost domain or range declarations. |
| Harness failed on `relationship_density` | Check whether relationship extraction, deduplication, or export produced fewer object properties relative to classes. |
| Harness failed on `attribute_richness` | Check whether datatype properties or attributes were lost or renamed. |
| Harness failed on `subclass_hierarchy_count` or `max_inheritance_depth` | Check whether the class hierarchy became flatter. |
| `Class Count` rose sharply | Check for over-extraction, prompt drift, or reduced deduplication. |
| `Class Count` fell sharply | Check input coverage, failed extraction, over-aggressive deduplication, or export failure. |
| Costs rose sharply | Check input size, model choice, retries, and cache behaviour. |
| Costs are near zero | Check whether the run skipped LLM calls, failed early, or did not process expected input. |
| Metrics row exists but harness columns are blank | Confirm the job was a harness run and that the harness could update the shared metrics CSV. |

## Technical Reference

The rest of this page is for maintainers or investigators who need the exact
artifact layout and implementation details.

### Main Artifact Layout

The exact path is controlled by the run configuration. The default harness
domain is `ontology-harness-baseline`. The bucket for this work is
`govuk-ai-accelerator-data-integration`.

```text
<domain>/
+-- output/
|   +-- owl_ontology_metrics.csv
+-- baselines/
|   +-- accepted.json
+-- run-YYYYMMDD-N/
    +-- bedrock_costs.csv
    +-- config.yaml
    +-- stdout.log
    +-- output/
        +-- graph.json
        +-- ontology.ttl
        +-- regression_report.json
        +-- schema.json
        +-- export_status.json
        +-- deduplication.jsonl
        +-- deduplication_summary.json
```

Default harness paths:

- `s3://govuk-ai-accelerator-data-integration/ontology-harness-baseline/config.yaml`
- `s3://govuk-ai-accelerator-data-integration/ontology-harness-baseline/input`
- `s3://govuk-ai-accelerator-data-integration/ontology-harness-baseline`
- `s3://govuk-ai-accelerator-data-integration/ontology-harness-baseline/baselines/accepted.json`

### How The Harness Runs

1. The Workflow schedules one harness job per deployment ID when
   `ONTOLOGY_HARNESS_ENABLED=true`.
2. The deployment ID comes from `ONTOLOGY_HARNESS_DEPLOYMENT_ID`.
3. The harness loads the harness config and runs the normal Generator pipeline
   against the harness domain.
4. The harness reads `baselines/accepted.json`.
5. It loads the baseline and candidate `ontology.ttl` files.
6. It rebuilds comparable metrics from both Turtle files.
7. It writes `regression_report.json` to the candidate run output folder.
8. It updates the candidate row in `owl_ontology_metrics.csv`.
9. It marks the harness job `completed` when the report passes, or `failed`
   when one or more regression checks fail.

### Supporting Diagnostic Files

#### `bedrock_costs.csv`

Typical columns:

- `status`
- `run_tag`
- `usage_tag`
- `model_id`
- `input_tokens`
- `output_tokens`
- `cache_read_tokens`
- `cache_write_tokens`
- `estimated_cost_usd`
- `estimated_cost_text`
- `start_time_utc`
- `end_time_utc`
- `error_code`
- `error_message`

#### `export_status.json`

Useful fields:

- `status`
- `mode`
- `format`
- `output_path`
- `schema_path`
- `graph_path`
- `completed_at`
- `timings`
- `total_seconds`

#### `deduplication_summary.json`

Useful fields:

- `total_entities_before`
- `total_entities_after`
- `total_merged`
- `merge_by_stage`
- `avg_similarity_semantic`
- `timestamp`

#### Processing Metadata

The Generator builds `OntologyOutput.metadata` with runtime and quality signals
including:

- extracted entity and relationship counts
- post-deduplication entity and relationship counts
- new entity and relationship type counts
- processing time
- LLM call counts
- token counts and estimated token counts
- estimated cost when price calculation is available
- stage timings
- throughput
- ontology shape metrics

Ontology shape metrics include placeholder type counts, auto-created entity
counts, same-type subclass relationship counts, concrete root type counts,
hierarchy depth, and relationship-type pressure.

### Source References

Workflow repository:

- Harness scheduling and comparison:
  `scripts/pipeline/ontology_harness.py`
- Ontology job orchestration:
  `scripts/pipeline/ontology_generator.py`
- Review Tests route:
  `govuk_ai_accelerator_app.py`
- Cross-repo overview:
  `docs/architecture/cross-repo-integration.md`

Generator repository:

- OWL metrics CSV writing:
  `taxonomy_ontology_accelerator/ontology_engine/storage/export.py`
- Regression thresholds and report shape:
  `taxonomy_ontology_accelerator/ontology_engine/evaluation/regression.py`
- Processing metadata and ontology shape metrics:
  `taxonomy_ontology_accelerator/ontology_engine/core/extraction_finalize.py`
  and `taxonomy_ontology_accelerator/ontology_engine/core/models.py`
- Generator production run book:
  `docs/ontology/RUNBOOK.md`

The cross-repository lifecycle is documented in
[docs/architecture/cross-repo-integration.md](../architecture/cross-repo-integration.md).
