"""Post-deployment ontology regression harness."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import fsspec
import yaml
from sqlalchemy.exc import IntegrityError

from scripts.ingestion.commands.utils import DEFAULT_S3_BUCKET
from scripts.pipeline.logging_config import logger
from scripts.pipeline.ontology_generator import (
    JobStoppedError,
    STOPPED_JOB_MESSAGE,
    STOPPED_JOB_STATUS,
    _persist_config_yaml,
    _update_job_status,
    run_ontology_pipeline,
)


HARNESS_PIPELINE = "ontology-harness"
DEFAULT_HARNESS_DOMAIN = "ontology-harness-baseline"
ONTOLOGY_METRICS_FILENAME = "owl_ontology_metrics.csv"
REGRESSION_REPORT_FILENAME = "regression_report.json"
HARNESS_METRICS_COLUMNS = [
    "Harness Result",
    "Harness Baseline Run ID",
    "Harness Deployment ID",
    "Harness Failed Metrics",
    "Harness Report URI",
]


@dataclass(frozen=True)
class HarnessSettings:
    domain: str
    deployment_id: str
    bucket_name: str
    config_uri: str
    baseline_manifest_uri: str

    @property
    def job_id(self) -> str:
        return f"{self.domain}:{self.deployment_id}"


def _is_harness_enabled() -> bool:
    return os.getenv("ONTOLOGY_HARNESS_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _build_harness_settings() -> HarnessSettings | None:
    domain = os.getenv("ONTOLOGY_HARNESS_DOMAIN", DEFAULT_HARNESS_DOMAIN)
    deployment_id = os.getenv("ONTOLOGY_HARNESS_DEPLOYMENT_ID", "").strip()
    if not deployment_id:
        logger.warning("[ontology-harness] enabled but ONTOLOGY_HARNESS_DEPLOYMENT_ID is unset")
        return None

    bucket_name = os.getenv("S3_BUCKET_NAME", DEFAULT_S3_BUCKET)
    config_uri = os.getenv(
        "ONTOLOGY_HARNESS_CONFIG_URI",
        f"s3://{bucket_name}/{domain}/config.yaml",
    )
    baseline_manifest_uri = os.getenv(
        "ONTOLOGY_HARNESS_BASELINE_MANIFEST_URI",
        f"s3://{bucket_name}/{domain}/baselines/accepted.json",
    )
    return HarnessSettings(
        domain=domain,
        deployment_id=deployment_id,
        bucket_name=bucket_name,
        config_uri=config_uri,
        baseline_manifest_uri=baseline_manifest_uri,
    )


def _load_harness_config(settings: HarnessSettings) -> dict[str, Any]:
    fs, path = fsspec.core.url_to_fs(settings.config_uri)
    with fs.open(path, "r") as config_file:
        config = yaml.safe_load(config_file) or {}
    if not isinstance(config, dict):
        raise ValueError(f"Harness config must be a mapping: {settings.config_uri}")
    return config


def _prepare_harness_config(config: dict[str, Any], settings: HarnessSettings) -> dict[str, Any]:
    prepared = json.loads(json.dumps(config))
    prepared["domain_name"] = settings.domain

    filesystem = prepared.setdefault("filesystem", {})
    filesystem.setdefault("protocol", "s3")

    path = prepared.setdefault("path", {})
    path["input_path"] = (
        os.getenv("ONTOLOGY_HARNESS_INPUT_PATH")
        or path.get("input_path")
        or prepared.get("input_path")
        or f"s3://{settings.bucket_name}/{settings.domain}/input"
    )
    path["output_dir"] = (
        os.getenv("ONTOLOGY_HARNESS_OUTPUT_DIR")
        or path.get("output_dir")
        or prepared.get("output_dir")
        or f"s3://{settings.bucket_name}/{settings.domain}"
    )

    harness_config = prepared.setdefault("harness", {})
    harness_config["deployment_id"] = settings.deployment_id
    harness_config["baseline_manifest_uri"] = settings.baseline_manifest_uri
    return prepared


def schedule_ontology_harness(app) -> str | None:
    """Enqueue the post-deployment ontology harness once for the deployed version."""
    if not _is_harness_enabled():
        logger.info("[ontology-harness] disabled")
        return None

    settings = _build_harness_settings()
    if settings is None:
        return None

    try:
        config = _prepare_harness_config(_load_harness_config(settings), settings)
    except Exception as exc:
        logger.error(f"[ontology-harness] unable to load harness config: {exc}")
        return None

    with app.app_context():
        from govuk_ai_accelerator_app import ProcessingJob, db

        existing_job = db.session.get(ProcessingJob, settings.job_id)
        if existing_job is not None:
            logger.info(f"[ontology-harness] job already queued job_id={settings.job_id}")
            return settings.job_id

        try:
            db.session.add(
                ProcessingJob(
                    id=settings.job_id,
                    status="pending",
                    pipeline=HARNESS_PIPELINE,
                    domain=settings.domain,
                    config_data=json.dumps(config),
                    domain_prompt=None,
                )
            )
            db.session.commit()
            logger.info(f"[ontology-harness] queued job_id={settings.job_id}")
            return settings.job_id
        except IntegrityError:
            db.session.rollback()
            logger.info(f"[ontology-harness] duplicate queue attempt job_id={settings.job_id}")
            return settings.job_id


def _read_text(uri: str) -> str:
    fs, path = fsspec.core.url_to_fs(uri)
    with fs.open(path, "r") as file_obj:
        content = file_obj.read()
    if isinstance(content, bytes):
        return content.decode("utf-8")
    return content


def _write_json(uri: str, payload: dict[str, Any]) -> None:
    fs, path = fsspec.core.url_to_fs(uri)
    parent = fs._parent(path)
    if parent:
        fs.makedirs(parent, exist_ok=True)
    with fs.open(path, "w") as file_obj:
        json.dump(payload, file_obj, indent=2, sort_keys=True)
        file_obj.write("\n")


def _write_text(uri: str, content: str) -> None:
    fs, path = fsspec.core.url_to_fs(uri)
    parent = fs._parent(path)
    if parent:
        fs.makedirs(parent, exist_ok=True)
    with fs.open(path, "w") as file_obj:
        file_obj.write(content)


def _load_baseline_manifest(uri: str) -> dict[str, Any]:
    manifest = json.loads(_read_text(uri))
    baseline_run_id = manifest.get("baseline_run_id")
    baseline_output_uri = manifest.get("baseline_output_uri")
    if not baseline_run_id or not baseline_output_uri:
        raise ValueError("Baseline manifest must include baseline_run_id and baseline_output_uri")
    return manifest


def _build_ontology_metrics_from_turtle(turtle_content: str | bytes) -> dict[str, float]:
    from taxonomy_ontology_accelerator.ontology_engine.evaluation.regression import (
        build_ontology_metrics_from_turtle,
    )

    return build_ontology_metrics_from_turtle(turtle_content)


def _compare_ontology_metrics(
    baseline_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any],
    **kwargs,
) -> dict[str, Any]:
    from taxonomy_ontology_accelerator.ontology_engine.evaluation.regression import (
        RegressionReportContext,
        compare_ontology_metrics,
    )

    context = RegressionReportContext(
        domain=kwargs.pop("domain"),
        deployment_version=kwargs.pop("deployment_version"),
        baseline_run_id=kwargs.pop("baseline_run_id"),
        baseline_output_uri=kwargs.pop("baseline_output_uri"),
        baseline_uri=kwargs.pop("baseline_uri"),
        candidate_run_id=kwargs.pop("candidate_run_id"),
        candidate_output_uri=kwargs.pop("candidate_output_uri"),
        candidate_uri=kwargs.pop("candidate_uri"),
        baseline_promoted_at=kwargs.pop("baseline_promoted_at", None),
        baseline_notes=kwargs.pop("baseline_notes", None),
    )
    return compare_ontology_metrics(baseline_metrics, candidate_metrics, context=context, **kwargs)


def _derive_job_runs(output_dir: str | None, job_id: str | None) -> str | None:
    if not output_dir:
        return job_id

    match = re.search(r"(run-\d{8}-\d*\/.*)", str(output_dir))
    if match:
        job_runs = match.group(1).rstrip("/")
        if job_runs.endswith("/output"):
            return job_runs[:-7]
        return job_runs
    return job_id


def _regression_error_message(report: dict[str, Any]) -> str | None:
    if report.get("passed"):
        return None

    failed_metrics = report.get("failed_metrics") or []
    if failed_metrics:
        return f"Ontology harness regression failed: {', '.join(failed_metrics)}"
    return "Ontology harness regression failed"


def _output_file_uri(output_dir: str, filename: str) -> str:
    return f"{output_dir.rstrip('/')}/{filename}"


def _ontology_metrics_csv_uri(candidate_output_uri: str) -> str:
    candidate_output_uri = str(candidate_output_uri).rstrip("/")
    if candidate_output_uri.endswith("/output"):
        run_uri = candidate_output_uri.removesuffix("/output")
        domain_uri = run_uri.rsplit("/", 1)[0]
        return f"{domain_uri}/output/{ONTOLOGY_METRICS_FILENAME}"
    return f"{candidate_output_uri}/{ONTOLOGY_METRICS_FILENAME}"


def _write_harness_summary_to_metrics_csv(
    candidate_output_uri: str,
    report: dict[str, Any],
    report_uri: str,
) -> None:
    metrics_csv_uri = _ontology_metrics_csv_uri(candidate_output_uri)
    candidate_run_id = str(report.get("candidate", {}).get("run_id") or "")
    if not candidate_run_id:
        logger.warning("[ontology-harness] unable to update metrics CSV: missing candidate run id")
        return

    try:
        existing_content = _read_text(metrics_csv_uri)
        reader = csv.DictReader(io.StringIO(existing_content))
        fieldnames = list(reader.fieldnames or [])
        if not fieldnames:
            logger.warning(f"[ontology-harness] metrics CSV has no header: {metrics_csv_uri}")
            return

        for column in HARNESS_METRICS_COLUMNS:
            if column not in fieldnames:
                fieldnames.append(column)

        rows = list(reader)
        summary = {
            "Harness Result": "PASS" if report.get("passed") else "FAIL",
            "Harness Baseline Run ID": str(report.get("baseline", {}).get("run_id") or ""),
            "Harness Deployment ID": str(
                report.get("deployment_id") or report.get("deployment_version") or ""
            ),
            "Harness Failed Metrics": ", ".join(report.get("failed_metrics") or []),
            "Harness Report URI": report_uri,
        }

        updated = False
        for row in rows:
            if row.get("Run ID") == candidate_run_id:
                row.update(summary)
                updated = True
                break

        if not updated:
            logger.warning(
                "[ontology-harness] metrics CSV row not found "
                f"run_id={candidate_run_id} uri={metrics_csv_uri}"
            )
            return

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        _write_text(metrics_csv_uri, output.getvalue())
        logger.info(f"[ontology-harness] updated metrics CSV uri={metrics_csv_uri}")
    except Exception as exc:
        logger.warning(f"[ontology-harness] unable to update metrics CSV: {exc}")


def run_ontology_harness_background_task(
    config: dict[str, Any],
    domain_prompt: str | None,
    job_id: str | None = None,
) -> bool:
    """Run ontology generation and compare the candidate output against the baseline."""
    try:
        output_dir = asyncio.run(
            run_ontology_pipeline(
                config_data=config,
                domain_prompt=domain_prompt,
                job_id=job_id,
            )
        )
        logger.info(f"[job={job_id}] ontology harness generation completed")

        if output_dir:
            _persist_config_yaml(config, str(output_dir))

        harness_config = config.get("harness", {})
        baseline_manifest_uri = harness_config.get("baseline_manifest_uri")
        if not baseline_manifest_uri:
            raise ValueError("Harness config is missing harness.baseline_manifest_uri")

        baseline_manifest = _load_baseline_manifest(baseline_manifest_uri)
        baseline_output_uri = baseline_manifest["baseline_output_uri"]
        baseline_ontology_uri = _output_file_uri(str(baseline_output_uri), "ontology.ttl")
        candidate_output_uri = str(output_dir)
        candidate_ontology_uri = _output_file_uri(candidate_output_uri, "ontology.ttl")
        job_runs = _derive_job_runs(candidate_output_uri, job_id)

        baseline_metrics = _build_ontology_metrics_from_turtle(_read_text(baseline_ontology_uri))
        candidate_metrics = _build_ontology_metrics_from_turtle(_read_text(candidate_ontology_uri))

        report = _compare_ontology_metrics(
            baseline_metrics,
            candidate_metrics,
            domain=config.get("domain_name", DEFAULT_HARNESS_DOMAIN),
            deployment_version=harness_config.get("deployment_id", ""),
            baseline_run_id=baseline_manifest["baseline_run_id"],
            baseline_output_uri=baseline_output_uri,
            baseline_uri=baseline_ontology_uri,
            baseline_promoted_at=baseline_manifest.get("promoted_at"),
            baseline_notes=baseline_manifest.get("notes"),
            candidate_run_id=job_runs or "",
            candidate_output_uri=candidate_output_uri,
            candidate_uri=candidate_ontology_uri,
        )
        report_uri = _output_file_uri(str(output_dir), REGRESSION_REPORT_FILENAME)
        _write_json(report_uri, report)
        _write_harness_summary_to_metrics_csv(candidate_output_uri, report, report_uri)

        error_message = _regression_error_message(report)
        if job_id:
            _update_job_status(
                job_id,
                "completed" if report.get("passed") else "failed",
                error_message=error_message,
                job_runs=job_runs,
                clear_lease=True,
            )
        return bool(report.get("passed"))
    except JobStoppedError as exc:
        logger.info(f"[job={job_id}] ontology harness stopped: {exc}")
        if job_id:
            _update_job_status(
                job_id,
                STOPPED_JOB_STATUS,
                error_message=STOPPED_JOB_MESSAGE,
                clear_lease=True,
            )
        return False
    except Exception as exc:
        logger.error(f"[job={job_id}] ontology harness failed error={exc}")
        if job_id:
            _update_job_status(job_id, "failed", error_message=str(exc), clear_lease=True)
        raise
