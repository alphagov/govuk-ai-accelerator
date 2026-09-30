# Docker

This project is designed to run with Docker Compose. It starts the PostgreSQL database and the app together, and keeps the app connected to the database using the internal Docker network.

You can develop against this stack without needing to install Python or Postgres on your host machine, the project root is mounted into the app container, and the app automatically reloads when you make changes. 

## Prerequisites

- Docker installed and running
- Docker Compose available (`docker compose`)

## Start everything

From the project root:

```bash
docker compose up --build -d
```

This will:
- build the app image
- start PostgreSQL a container, accessible on port `9432`
- start the app on port `3000`
- run in the background

Open the app here http://localhost:3000

## Useful commands

### View logs

```bash
docker compose logs -f
```

To view only the app logs:

```bash
docker compose logs -f app
```

To view only the database logs:

```bash
docker compose logs -f db
```

### Stop everything

```bash
docker compose down
```

This stops both containers without deleting the database volume.

## Remove everything including database data

```bash
docker compose down -v
```

This removes the app and database containers plus the persistent Postgres data volume.

## Set environment variables

If your build or runtime needs GitHub or AWS credentials, set them before running `docker compose`:

```bash
export AWS_REGION=eu-west-1
export AWS_DEFAULT_REGION=eu-west-1
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_SESSION_TOKEN=your_session_token_if_required
```

Then start the stack:

```bash
docker compose up --build -d
```

### Persisting environment variables

You can edit and set the values in the `.env` file in the project root. Docker Compose will automatically load these values when starting the containers.

```dotenv
# PROJECT_ROOT/.env
AWS_REGION=eu-west-1
AWS_DEFAULT_REGION=eu-west-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_SESSION_TOKEN=your_session_token_if_required
```

## Rebuild after code changes

File changes __should__ be reflected in the running app without rebuilding, but if you need to rebuild the app image (for example after changing dependencies), run:

```bash
docker compose up --build -d
```

## Useful commands

Rebuild without cache:

```bash
docker compose build --no-cache
```

Restart the app only:

```bash
docker compose restart app
```

Restart the database only:

```bash
docker compose restart db
```

## Notes

- The database container is named `govuk-postgres`
- The app container is named `ontology-app`
- The app uses port `3000`
- PostgreSQL is exposed on host port `9432`
- Compose uses the database service name `db` internally, so the app connects using `db:5432` rather than `localhost`
