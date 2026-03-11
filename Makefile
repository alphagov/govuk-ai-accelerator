# Variables
GITHUB_TOKEN   ?= $(error GITHUB_TOKEN is not set. Run: make up GITHUB_TOKEN=<your token>)
IMAGE_NAME      = ontology-app
CONTAINER_NAME  = ontology-app
DB_NAME         = govuk-postgres
NETWORK_NAME    = govuk-network
APP_PORT        = 3000
DB_URL          = postgresql://govuk_ai_accelerator_user@$(DB_NAME):5432/govuk_ai_accelerator
LOCAL_DB_URL    = postgresql://govuk_ai_accelerator_user@localhost:5432/govuk_ai_accelerator

.PHONY: up down run docker-build docker-run docker-stop db-start db-stop clean docker-shell shell

up: docker-stop db-start docker-build docker-run

## Stop everything: app + db
down: docker-stop db-stop

## Run the app locally (starts app with localhost DB connection)
run:
	DATABASE_URL="$(LOCAL_DB_URL)" uv run govuk_ai_accelerator_app.py

## Start a local Postgres container
db-start:
	@docker network inspect $(NETWORK_NAME) > /dev/null 2>&1 || docker network create $(NETWORK_NAME)
	@docker inspect $(DB_NAME) > /dev/null 2>&1 \
	  && echo "$(DB_NAME) already running" \
	  || docker run -d \
	       --name $(DB_NAME) \
	       --network $(NETWORK_NAME) \
	       -e POSTGRES_USER=govuk_ai_accelerator_user \
	       -e POSTGRES_DB=govuk_ai_accelerator \
	       -e POSTGRES_HOST_AUTH_METHOD=trust \
	       -p 5432:5432 \
	       postgres:15

## Stop and remove the local Postgres container
db-stop:
	@docker rm -f $(DB_NAME) 2>/dev/null || true

## Build the Docker image (Force no-cache to ensure fresh code/dependencies)
docker-build:
	@echo "Removing old image to ensure a fresh start..."
	@docker rmi -f $(IMAGE_NAME) 2>/dev/null || true
	docker build \
	  --no-cache \
	  --pull \
	  --build-arg GITHUB_TOKEN=$(GITHUB_TOKEN) \
	  -t $(IMAGE_NAME) .

## Run the Docker image (foreground)
docker-run:
	docker run --name $(CONTAINER_NAME) \
	  --network $(NETWORK_NAME) \
	  -p $(APP_PORT):$(APP_PORT) \
	  -e DATABASE_URL="$(DB_URL)" \
	  -e AWS_REGION \
	  -e AWS_DEFAULT_REGION \
	  -e AWS_ACCESS_KEY_ID \
	  -e AWS_SECRET_ACCESS_KEY \
	  -e AWS_SESSION_TOKEN \
	  $(IMAGE_NAME)

## Enter the running container to explore folders
docker-shell:
	docker exec -it $(CONTAINER_NAME) /bin/bash || docker exec -it $(CONTAINER_NAME) /bin/sh

## Shorthand for docker-shell
shell: docker-shell

## Stop and remove the app container
docker-stop:
	@docker rm -f $(CONTAINER_NAME) 2>/dev/null || true

## Optional: Clean up all unused docker data
clean: docker-stop db-stop
	docker system prune -f

clean-local:
	rm -rf .venv uv.lock .python-version pyproject.toml s3: domains .ontology_runs