GITHUB_TOKEN   ?= $(error GITHUB_TOKEN is not set. Run: make up GITHUB_TOKEN=<your token>)
IMAGE_NAME      = ontology-app
CONTAINER_NAME  = ontology-app
DB_NAME         = govuk-postgres
APP_PORT        = 3000
DB_URL          = postgresql://govuk_ai_accelerator_user@host.docker.internal:5432/govuk_ai_accelerator

.PHONY: up down run docker-build docker-run docker-stop db-start db-stop

## Start everything: db + build + run (pass GITHUB_TOKEN=<token>)
up: docker-stop db-start docker-build docker-run

## Stop everything: app + db
down: docker-stop db-stop

## Run the app locally (requires: source environment.sh)
run:
	uv run govuk_ai_accelerator_app.py

## Start a local Postgres container (passwordless, dev only)
db-start:
	@docker inspect $(DB_NAME) > /dev/null 2>&1 \
	  && echo "$(DB_NAME) already running" \
	  || docker run -d \
	       --name $(DB_NAME) \
	       -e POSTGRES_USER=govuk_ai_accelerator_user \
	       -e POSTGRES_DB=govuk_ai_accelerator \
	       -e POSTGRES_HOST_AUTH_METHOD=trust \
	       -p 5432:5432 \
	       postgres:15

## Stop and remove the local Postgres container
db-stop:
	@docker rm -f $(DB_NAME) 2>/dev/null || true

## Build the Docker image
docker-build:
	docker build \
	  --build-arg GITHUB_TOKEN=$(GITHUB_TOKEN) \
	  -t $(IMAGE_NAME) .

## Run the Docker image (foreground)
docker-run:
	docker run --name $(CONTAINER_NAME) \
	  -p $(APP_PORT):$(APP_PORT) \
	  --add-host=host.docker.internal:host-gateway \
	  -e DATABASE_URL="$(DB_URL)" \
	  -e AWS_REGION \
	  -e AWS_DEFAULT_REGION \
	  -e AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY \
	  -e AWS_SESSION_TOKEN \
	  $(IMAGE_NAME)

## Stop and remove the app container
docker-stop:
	@docker rm -f $(CONTAINER_NAME) 2>/dev/null || true
