# GOV.UK AI Generator

A Python Flask application for asynchronous ontology generation using the `taxonomy-ontology-accelerator` library.

## Local Setup

### Prerequisites

- **Python 3.13** - managed via `uv`
- **uv** — Python package manager
- **PostgreSQL** - local instance or Docker
- **AWS credentials** - available in the environment (for S3/Bedrock access)
- **GitHub token** — with read access to `alphagov/govuk-ai-accelerator-tw-accelerator` (private package)

Install `uv` if not already installed:

```bash
brew install uv
# or
pip install uv
```

---

### 1. Install dependencies

```bash
uv init --python 3.13
uv python pin 3.13
uv add -r requirements.txt
uv add "git+https://x-access-token:<GITHUB_TOKEN>@github.com/alphagov/govuk-ai-accelerator-tw-accelerator.git"
```

The default dependency set now includes `faiss-cpu`, so semantic deduplication can use FAISS when the configured threshold is reached. If you already have an existing virtualenv, run `uv sync` after pulling these changes.

---

### 2. Set up PostgreSQL

**Option A — Homebrew (if Postgres is already installed locally):**


```bash
# Create the user (no password) and database
psql postgres -c "CREATE USER govuk_ai_accelerator_user;"
psql postgres -c "CREATE DATABASE govuk_ai_accelerator OWNER govuk_ai_accelerator_user;"
psql postgres -c "GRANT ALL ON SCHEMA public TO govuk_ai_accelerator_user;"
```

**Option B — Docker:**

```bash
docker run -d \
  --name govuk-postgres \
  -e POSTGRES_USER=govuk_ai_accelerator_user \
  -e POSTGRES_DB=govuk_ai_accelerator \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  -p 5432:5432 \
  postgres:15
```

> `POSTGRES_HOST_AUTH_METHOD=trust` disables password auth — fine for local development, never use in production.
---

### 3. Configure environment

```bash
source environment.sh
```

This sets `DATABASE_URL=postgresql://govuk_ai_accelerator_user@localhost:5432/govuk_ai_accelerator` (no password). Also export your AWS credentials:

```bash
export AWS_REGION=eu-west-2
export AWS_ACCESS_KEY_ID=<your key>
export AWS_SECRET_ACCESS_KEY=<your secret>
export AWS_SESSION_TOKEN=<your token>  # if using temporary credentials


```

---

### 4. Run the app

**Debug mode (Flask dev server):**

```bash
uv run govuk_ai_accelerator_app.py
```

**Production mode (Waitress WSGI server):**

```bash
uv run waitress-serve --port 3000 --call 'govuk_ai_accelerator_app:create_app'
```

The app runs on **http://localhost:3000**.

> **Note:** If the database is unavailable, the app starts anyway but job status tracking is disabled. A warning will appear in the logs.

---

## Ontology Harness Baseline

The post-deployment ontology harness runs the normal generator against a dedicated
baseline domain and compares the candidate output against a promoted baseline run.
It is disabled by default.

Required environment:

```bash
export ONTOLOGY_HARNESS_ENABLED=true
export ONTOLOGY_HARNESS_DEPLOYMENT_ID=<release-tag-or-git-sha>
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
check independently. The deployment workflow bakes this into the Docker image as
the matching release tag when available, otherwise the resolved commit SHA. The
candidate output remains a normal run-numbered generator output. The harness
writes `regression_report.json` to the candidate run output folder and the
Historical Jobs page links to the run artifacts and report, including failed
regression checks.

To promote a new accepted baseline, update `baselines/accepted.json` to point to
the chosen run. The run itself should not be moved or overwritten.

---

## Docker

Build and run using Docker (requires a GitHub token for the private package):

```bash
docker build --build-arg GITHUB_TOKEN=<your gh token> -t ontology-app .

docker run -p 3000:3000 \
  --add-host=host.docker.internal:host-gateway \
  -e DATABASE_URL="postgresql://govuk_ai_accelerator_user@host.docker.internal:5432/govuk_ai_accelerator" \
  -e AWS_REGION \
  -e AWS_DEFAULT_REGION \
  -e AWS_ACCESS_KEY_ID \
  -e AWS_SECRET_ACCESS_KEY \
  -e AWS_SESSION_TOKEN \
  ontology-app
```

Rebuild the image after pulling dependency changes so the container picks up `faiss-cpu` from `requirements.txt`.

> **Note for Mac users:**  Inside Docker, use `host.docker.internal` (not `localhost`) in `DATABASE_URL` to reach a Postgres instance running on your Mac.

---
## Using Makefile setup
 For quick local development setup to run application in docker, you can run the 
```
```bash
make up GITHUB_TOKEN=<your-github-token>
```
```

```
```
```
```
``` 

```
```
```
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
