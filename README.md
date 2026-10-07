# GOV.UK AI Generator

A Python Flask application for asynchronous ontology generation using the `taxonomy-ontology-accelerator` library.

## Cross-Repo Ontology Lifecycle

For a technical overview of how the Workflow, Generator, Ontology Validator,
Data Science Repo, and Content Workflow fit together, see
[docs/architecture/cross-repo-integration.md](docs/architecture/cross-repo-integration.md).

## Run Books

- [Ontology Generator Metrics Run Book](docs/runbooks/ontology-generator-metrics.md)

---

## TLDR; Run everything in containers (Docker Compose)

This will stand up the app with the project root mounted inside the container, so you can edit files on your host and see the changes reflected in the app without needing to rebuild the image.

See a more detailed explanation of the Docker setup in [DOCKER.md](DOCKER.md).

### Prerequisites

- Docker installed and running
- Docker Compose available (`docker compose`)

### Start everything

```bash
docker compose up --build -d
```

---

## Ontology Harness Baseline

The post-deployment ontology harness runs the normal Generator against a dedicated
baseline domain and compares the candidate output against a promoted baseline run.
It is disabled by default.

Required environment:

```bash
export ONTOLOGY_HARNESS_ENABLED=true
export ONTOLOGY_HARNESS_DEPLOYMENT_ID=tw-accelerator-<generator-git-sha>
```

Optional environment:

```bash
export ONTOLOGY_HARNESS_DOMAIN=ontology-harness-baseline
export ONTOLOGY_HARNESS_CONFIG_URI=s3://<bucket>/ontology-harness-baseline/config.yaml
export ONTOLOGY_HARNESS_BASELINE_MANIFEST_URI=s3://<bucket>/ontology-harness-baseline/baselines/accepted.json
```

The accepted baseline is a manifest that points to an immutable generator run:

```json
{
  "baseline_run_id": "run-20260520-1",
  "baseline_output_uri": "s3://bucket/ontology-harness-baseline/run-20260520-1/output",
  "promoted_at": "2026-05-20T14:00:00Z",
  "notes": "Accepted baseline after CSMD-339 metric changes"
}
```

Each deployment queues one harness job using the key
`ontology-harness-baseline:<deployment-id>`, so multiple pods do not run the same
check independently. The deployment workflow resolves the current
`govuk-ai-accelerator-tw-accelerator` `main` commit SHA, pins the Docker image to
install that Generator revision, and uses `tw-accelerator-<generator-git-sha>` as
the harness deployment ID. Workflow-only deploys therefore reuse the same harness
job key until the Generator commit changes. The candidate output remains a normal
run-numbered Generator output. The harness writes `regression_report.json` to the
candidate run output folder and the Historical Jobs page links to the run
artifacts and report, including failed regression checks.
It also summarises the result on the candidate row in
`output/owl_ontology_metrics.csv` using the `Harness Result`,
`Harness Baseline Run ID`, `Harness Deployment ID`, `Harness Failed Metrics`,
and `Harness Report URI` columns.

To promote a new accepted baseline, update `baselines/accepted.json` to point to
the chosen run. The run itself should not be moved or overwritten.

---

## API Reference

All endpoints are available at **http://localhost:3000**.

### Health Check

```
GET /healthcheck/ready
```

Returns `{"status": "healthy", "message": "Application is ready"}` when the app is running.

---

### Ontology UI

```
GET /ontology/
```

Web interface for submitting ontology processing jobs via file upload.

---

### Submit Ontology Job

```
POST /ontology/submit
```

Accepts a YAML config file and optional domain prompt. Returns a job ID immediately for async status polling.

```bash
curl -X POST http://localhost:3000/ontology/submit \
  -F "file=@config.yaml" \
  -F "text_file=@domain_prompt.txt"
```

Response (`202 Accepted`):
```json
{"job_id": "<uuid>", "status": "pending"}
```

---

### Check Job Status

```
GET /ontology/status/<job_id>
```

```bash
curl http://localhost:3000/ontology/status/<job_id>
```

Response:
```json
{"job_id": "<uuid>", "status": "pending|completed|failed"}
```

---

## Tests

```bash
uv run pytest
```

---

## Licence

[MIT LICENCE](LICENCE)
