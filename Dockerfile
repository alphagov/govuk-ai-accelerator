#FROM --platform=linux/arm64/v8 python:3.13-slim-bookworm AS base
FROM python:3.13-slim-bookworm AS base

ENV GOVUK_APP_NAME=GOVUK-AI-ACCELERATOR

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    libcurl4 \
    curl \
    postgresql-client \
    && apt-get -y clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

WORKDIR /app  
COPY requirements.txt .

RUN echo "Installing python requirements" && \
    pip --no-cache-dir install -r requirements.txt

COPY . .
EXPOSE 8080 

CMD ["waitress-serve", "--port", "3000", "--call", "govuk_ai_accelerator_app:create_app"]  