# FROM --platform=linux/arm64/v8 python:3.13-slim-bookworm AS base
FROM python:3.13-slim-bookworm AS base

ARG ONTOLOGY_HARNESS_ENABLED=false
ARG ONTOLOGY_HARNESS_DEPLOYMENT_ID=""
ARG GENERATOR_GIT_REF=main

ENV GOVUK_APP_NAME=GOVUK-AI-ACCELERATOR
ENV UV_CACHE_DIR=/tmp/.uv_cache
ENV ONTOLOGY_HARNESS_ENABLED=${ONTOLOGY_HARNESS_ENABLED}
ENV ONTOLOGY_HARNESS_DEPLOYMENT_ID=${ONTOLOGY_HARNESS_DEPLOYMENT_ID}
# ARG GITHUB_TOKEN

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    libcurl4 \
    curl \
    postgresql-client \
    pandoc \
    git \
    && apt-get -y clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

WORKDIR /app  

RUN pip install --no-cache-dir uv

COPY requirements.txt .

COPY requirements.txt .
RUN uv pip install --system -r requirements.txt
# RUN uv pip install --system "git+https://x-access-token:${GITHUB_TOKEN}@github.com/alphagov/govuk-ai-accelerator-tw-accelerator.git" \
#     && rm -rf /root/.cache/uv

RUN \
    --mount=type=secret,id=GITHUB_TOKEN,env=GITHUB_TOKEN \
    git config --global url."https://x-access-token:${GITHUB_TOKEN}@github.com/".insteadOf "https://github.com/" && \
    uv pip install --system "git+https://github.com/alphagov/govuk-ai-accelerator-tw-accelerator@${GENERATOR_GIT_REF}" && \
    rm -rf /root/.cache/uv

COPY . .

EXPOSE 8080 


CMD ["waitress-serve", "--host=0.0.0.0", "--port=3000", "--call", "govuk_ai_accelerator_app:create_app"]
