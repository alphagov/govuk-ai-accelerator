FROM python:3.13-slim-bookworm AS base

ARG ONTOLOGY_HARNESS_ENABLED=false
ARG ONTOLOGY_HARNESS_DEPLOYMENT_ID=""
ARG GENERATOR_GIT_REF=main
ARG GITHUB_TOKENENV

ENV GOVUK_APP_NAME=GOVUK-AI-ACCELERATOR
ENV UV_CACHE_DIR=/tmp/.uv_cache
ENV ONTOLOGY_HARNESS_ENABLED=${ONTOLOGY_HARNESS_ENABLED}
ENV ONTOLOGY_HARNESS_DEPLOYMENT_ID=${ONTOLOGY_HARNESS_DEPLOYMENT_ID}
ENV UV_CACHE_DIR=/root/.cache/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libcurl4 \
       curl \
       postgresql-client \
       pandoc \
       git \
    && apt-get -y clean \
    && rm -rf /var/lib/apt/lists/* /tmp/*

WORKDIR /app

# Copy the uv project metadata, not the legacy requirements file
COPY pyproject.toml uv.lock ./

RUN --mount=type=secret,id=GITHUB_TOKEN,env=GITHUB_TOKEN \
    pip install --no-cache-dir uv && \
    mkdir -p lib && \
    git config --global url."https://x-access-token:${GITHUB_TOKEN}@github.com/".insteadOf "https://github.com/" && \
    git clone "https://x-access-token:${GITHUB_TOKEN}@github.com/alphagov/govuk-ai-accelerator-tw-accelerator.git" /tmp && \
    cd /tmp && \
    git checkout ${GENERATOR_GIT_REF} && \
    uv sync && \
    uv build --wheel --out-dir /app/lib && \
    uv sync --frozen --no-install-project

# Install the app itself
COPY . .
RUN uv sync --upgrade-package taxonomy-ontology-accelerator

EXPOSE 8080

FROM base AS development
CMD ["uv", "run", "uvicorn", "govuk_ai_accelerator_app:create_asgi_app", "--factory", "--reload", "--host", "0.0.0.0", "--port", "3000"]

FROM development AS production
CMD ["uv", "run", "waitress-serve", "--host=0.0.0.0", "--port=3000", "--call", "govuk_ai_accelerator_app:create_app"]
