#FROM --platform=linux/arm64/v8 python:3.13-slim-bookworm AS base
FROM python:3.13-slim-bookworm AS base

ENV GOVUK_APP_NAME=GOVUK-AI-ACCELERATOR
ARG GITHUB_TOKEN



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
RUN uv init

COPY requirements.txt .
RUN uv pip install --system -r requirements.txt
RUN uv pip install --system "git+https://${GITHUB_TOKEN}@github.com/alphagov/govuk-ai-accelerator-tw-accelerator"


COPY . .
COPY ./environment.sh /environment.sh
RUN chmod +x /environment.sh

EXPOSE 8080 

ENTRYPOINT ["/bin/bash", "-c", "source /environment.sh && \"$@\"", "--"]

CMD ["uv", "run", "waitress-serve", "--host=0.0.0.0", "--port=8080", "--call", "govuk_ai_accelerator_app:create_app"]