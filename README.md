# GOV.UK AI Generator

A Python Flask application for asynchronous ontology generation using the `taxonomy-ontology-accelerator` library.

## Local Setup

### Prerequisites

- **Python 3.13** — managed via `uv`
- **uv** — Python package manager
- **PostgreSQL** — local instance or Docker
- **AWS credentials** — available in the environment (for S3/Bedrock access)
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

> **Note:** Inside Docker, use `host.docker.internal` (not `localhost`) in `DATABASE_URL` to reach a Postgres instance running on your Mac.

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
