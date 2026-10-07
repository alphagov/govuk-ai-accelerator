FROM python:3.14-slim-bookworm AS development

ARG ONTOLOGY_HARNESS_ENABLED=false
ARG ONTOLOGY_HARNESS_DEPLOYMENT_ID=""

ENV GOVUK_APP_NAME=GOVUK-AI-ACCELERATOR
ENV UV_CACHE_DIR=/tmp/.uv_cache
ENV ONTOLOGY_HARNESS_ENABLED=${ONTOLOGY_HARNESS_ENABLED}
ENV ONTOLOGY_HARNESS_DEPLOYMENT_ID=${ONTOLOGY_HARNESS_DEPLOYMENT_ID}

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

RUN pip install --no-cache-dir uv
RUN mkdir lib

# Copy the uv project metadata, not the legacy requirements file
COPY pyproject.toml uv.lock ./
# Copy in the pre-built wheel for the taxonomy ontology accelerator library
COPY  lib/taxonomy_ontology_accelerator-*-py3-none-any.whl ./lib/

# Install dependencies without installing the project itself yet
RUN uv sync --frozen --no-install-project

# Install the app itself
COPY . .
RUN uv sync --frozen

EXPOSE 8080
CMD ["uv", "run", "uvicorn", "govuk_ai_accelerator_app:create_asgi_app", "--factory", "--reload", "--host", "0.0.0.0", "--port", "3000"]

FROM development AS production
CMD ["uv", "run", "waitress-serve", "--host=0.0.0.0", "--port=3000", "--call", "govuk_ai_accelerator_app:create_app"]
