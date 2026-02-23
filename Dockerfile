# FROM --platform=linux/arm64/v8 python:3.13-slim-bookworm AS base
FROM python:3.13-slim-bookworm AS base

ENV GOVUK_APP_NAME=GOVUK-AI-ACCELERATOR
ENV UV_CACHE_DIR=/tmp/.uv_cache
# ARG GOVUK_CI_GITHUB_API_TOKEN

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    libcurl4 \
    curl \
    postgresql-client \
    git \
    && apt-get -y clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

WORKDIR /app  

RUN pip install --no-cache-dir uv

COPY requirements.txt .

COPY requirements.txt .
RUN uv pip install --system -r requirements.txt
# RUN uv pip install --system "git+https://${GOVUK_CI_GITHUB_API_TOKEN}@github.com/alphagov/govuk-ai-accelerator-tw-accelerator"

RUN --mount=type=secret,id=GITHUB_TOKEN,env=GITHUB_TOKEN \
    git config --global url."https://x-access-token:${GITHUB_TOKEN}@github.com/".insteadOf "https://github.com/" && \
    uv pip install --system "git+https://github.com/alphagov/govuk-ai-accelerator-tw-accelerator"

COPY . .

EXPOSE 8080 

ENTRYPOINT ["/bin/bash", "-c", "source /environment.sh && \"$@\"", "--"]

CMD ["uv", "run", "waitress-serve", "--host=0.0.0.0", "--port=8080", "--call", "govuk_ai_accelerator_app:create_app"]