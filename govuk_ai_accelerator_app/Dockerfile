FROM --platform=linux/arm64/v8 python:3.13-slim-bookworm AS base

ENV GOVUK_APP_NAME=GOVUK-AI-ACCELERATOR

WORKDIR /app  
COPY requirements.txt .

RUN echo "Installing python requirements" && \
    pip --no-cache-dir install -r requirements.txt

COPY . .
EXPOSE 5000 

CMD ["python", "govuk_ai_accelerator_app.py"]  