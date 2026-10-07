
# Native Python Setup

Running the app natively makes it far easier to attach debuggers etc to the Python process.

## Prerequisites

- **Python 3.14** - managed via `uv`
- **uv** — Python package manager
- **Docker** — for running Postgres or the app in a container
- **AWS credentials** - available in the environment (for S3/Bedrock access)

Install `uv` if not already installed:

```bash
brew install uv
# or
pip install uv
```

---

## Install dependencies

```bash
uv python pin 3.14
uv sync --frozen
```

The default dependency set now includes `faiss-cpu`, so semantic deduplication can use FAISS when the configured threshold is reached. If you already have an existing virtualenv, run `uv sync` after pulling these changes.

---

## Configure environment

```bash
export AWS_REGION=eu-west-1
export AWS_DEFAULT_REGION=eu-west-1
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_SESSION_TOKEN=your_session_token_if_required
```

---

## Run the app locally (native Python)

### Start the database

```bash
docker compose up -d db
```

Then the database is available on postgresql://govuk_ai_accelerator_user@localhost:9432/govuk_ai_accelerator

### Debug mode (Flask dev server)

```bash
uv run govuk_ai_accelerator_app.py
```

### Production mode (Waitress WSGI server)

```bash
uv run waitress-serve --port 3000 --call 'govuk_ai_accelerator_app:create_app'
```

The app runs on **http://localhost:3000**.

> **Note:** If the database is unavailable, the app starts anyway but job status tracking is disabled. A warning will appear in the logs.
