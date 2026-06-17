"""GOV.UK AI Accelerator Flask Application."""

import os
import io
import json
import re
import zipfile
import uvicorn
import yaml
import boto3
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlparse
from flask import Flask, request, jsonify, render_template, Blueprint, Response, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate, upgrade
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, or_
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.exc import OperationalError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from scripts.pipeline.ontology_harness import schedule_ontology_harness
from scripts.pipeline.task_manager import start_task_manager
from scripts.pipeline.logging_config import configure_logging
from scripts.pipeline.utils import error_response, is_yaml_file, executor
from scripts.pipeline.constants import APP_HOST, APP_PORT, BLUEPRINTS
from scripts.ingestion.commands.utils import DEFAULT_S3_BUCKET
from scripts.ingestion.ingestion_pipeline import run_ingestion_background_task
from src.aws_helper import create_bucket_folder
from flask import current_app

from starlette.routing import Mount, Route
from a2wsgi import ASGIMiddleware, WSGIMiddleware

from src.web_browser.routing import get_domain_list

try:
    from taxonomy_ontology_accelerator.web import app as visualizer_app
    VISUALIZER_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    visualizer_app = None
    VISUALIZER_IMPORT_ERROR = exc

db = SQLAlchemy()
migrate = Migrate()
DEFAULT_DOMAIN_PROMPT = "#"
FINGERPRINTED_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"
DEFAULT_CONFIG_TEMPLATE_PATH = (
    Path(__file__).resolve().parent
    / "static"
    / "assets"
    / "templates"
    / "config-template.yaml"
)

PROTECTED_REVIEW_DOMAIN_NAMES = {"ontology-harness-baseline"}


class ProcessingJob(db.Model):
    """Model to track the status of submitted jobs."""

    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String)
    pipeline: Mapped[str] = mapped_column(String, default="ontology", nullable=True)
    domain: Mapped[str] = mapped_column(String, nullable=True)
    config_data: Mapped[str] = mapped_column(String, nullable=True, default=None)
    domain_prompt: Mapped[str] = mapped_column(String, nullable=True, default=None)
    job_runs: Mapped[str] = mapped_column(String, nullable=True)
    error_message: Mapped[str] = mapped_column(String, nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class ProcessingJobNote(db.Model):
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("processing_job.id"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


def _serialize_job_datetime(value: datetime | None) -> str | None:
    """Return job datetimes as explicit UTC instants for browser parsing."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _parse_note_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialize_job_note(note: ProcessingJobNote) -> dict:
    return {
        "id": note.id,
        "job_id": note.job_id,
        "text": note.text,
        "created_at": _serialize_job_datetime(note.created_at),
        "updated_at": _serialize_job_datetime(note.updated_at),
    }


def _note_metadata_for_jobs(job_ids: list[str]) -> dict[str, dict]:
    metadata = {
        job_id: {"notes_count": 0, "latest_note": None}
        for job_id in job_ids
    }
    if not job_ids:
        return metadata

    notes = (
        db.session.query(ProcessingJobNote)
        .filter(ProcessingJobNote.job_id.in_(job_ids))
        .order_by(ProcessingJobNote.created_at.asc(), ProcessingJobNote.id.asc())
        .all()
    )
    for note in notes:
        metadata[note.job_id]["notes_count"] += 1
        metadata[note.job_id]["latest_note"] = _serialize_job_note(note)
    return metadata


def _serialize_job(job: ProcessingJob, note_metadata: dict[str, dict] | None = None) -> dict:
    metadata = (note_metadata or {}).get(job.id, {"notes_count": 0, "latest_note": None})
    return {
        "job_id": job.id,
        "pipeline": job.pipeline,
        "domain": job.domain,
        "status": job.status,
        "job_runs": job.job_runs,
        "error": job.error_message,
        "created_at": _serialize_job_datetime(job.created_at),
        "notes_count": metadata["notes_count"],
        "latest_note": metadata["latest_note"],
        "visualize_url": _visualizer_run_url(job),
        "ontology_download_url": _ontology_download_url(job),
    }


def _serialize_domain_job(job: ProcessingJob, note_metadata: dict[str, dict] | None = None) -> dict:
    metadata = (note_metadata or {}).get(job.id, {"notes_count": 0, "latest_note": None})
    return {
        "job_id": job.id,
        "domain": job.domain,
        "status": job.status,
        "error": job.error_message,
        "created_at": _serialize_job_datetime(job.created_at),
        "notes_count": metadata["notes_count"],
        "latest_note": metadata["latest_note"],
    }


def _legacy_notes_key(job: ProcessingJob) -> str | None:
    if job.job_runs and job.domain:
        return f"{job.domain}/{job.job_runs}/notes.json"
    return None


def _read_legacy_s3_notes(job: ProcessingJob) -> list[dict]:
    key = _legacy_notes_key(job)
    if not key:
        return []

    s3_client = boto3.client("s3")
    try:
        response = s3_client.get_object(
            Bucket="govuk-ai-accelerator-data-integration",
            Key=key,
        )
        raw_notes = response["Body"].read().decode("utf-8")
        notes = json.loads(raw_notes)
    except Exception as exc:
        current_app.logger.info("No legacy notes imported for %s: %s", job.id, exc)
        return []

    if not isinstance(notes, list):
        return []
    return [note for note in notes if isinstance(note, dict) and str(note.get("text", "")).strip()]


def _import_legacy_notes_if_empty(job: ProcessingJob) -> None:
    existing_count = (
        db.session.query(ProcessingJobNote)
        .filter(ProcessingJobNote.job_id == job.id)
        .count()
    )
    if existing_count:
        return

    for legacy_note in _read_legacy_s3_notes(job):
        created_at = _parse_note_datetime(
            legacy_note.get("created_at") or legacy_note.get("timestamp")
        )
        db.session.add(
            ProcessingJobNote(
                job_id=job.id,
                text=str(legacy_note["text"]).strip(),
                created_at=created_at,
                updated_at=created_at,
            )
        )
    db.session.commit()


def _notes_for_job(job: ProcessingJob) -> list[ProcessingJobNote]:
    _import_legacy_notes_if_empty(job)
    return (
        db.session.query(ProcessingJobNote)
        .filter(ProcessingJobNote.job_id == job.id)
        .order_by(ProcessingJobNote.created_at.asc(), ProcessingJobNote.id.asc())
        .all()
    )


def _note_text_from_payload(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    text = str(payload.get("text", "")).strip()
    return text or None


def _default_bucket_name() -> str:
    return os.getenv("S3_BUCKET_NAME", DEFAULT_S3_BUCKET)


def _quoted_download_url(bucket_name: str, key: str) -> str:
    return f"/viewer/bucket/download/buckets/{quote(bucket_name)}/{quote(key, safe='/')}"


def _folder_download_url(job_id: str, bucket_name: str, prefix: str) -> str:
    return (
        f"/ontology/jobs/{quote(job_id)}/downloads/folder"
        f"?bucket={quote(bucket_name)}&prefix={quote(prefix, safe='')}"
    )


def _local_file_download_url(job_id: str, path: Path, filename: str | None = None) -> str:
    url = f"/ontology/jobs/{quote(job_id)}/downloads/local-file?path={quote(str(path), safe='')}"
    if filename:
        url += f"&filename={quote(filename, safe='')}"
    return url


def _s3_file_download_url(job_id: str, bucket_name: str, key: str, filename: str | None = None) -> str:
    url = (
        f"/ontology/jobs/{quote(job_id)}/downloads/s3-file"
        f"?bucket={quote(bucket_name)}&key={quote(key, safe='')}"
    )
    if filename:
        url += f"&filename={quote(filename, safe='')}"
    return url


def _local_folder_download_url(job_id: str, path: Path) -> str:
    return f"/ontology/jobs/{quote(job_id)}/downloads/local-folder?path={quote(str(path), safe='')}"


def _artifact_row(
    name: str,
    download_url: str,
    kind: str = "file",
    size: int | None = None,
    download_label: str = "Download",
    visualize_url: str | None = None,
) -> dict:
    artifact = {
        "name": name,
        "kind": kind,
        "size": size,
        "action": "download",
        "download_url": download_url,
        "download_label": download_label,
    }
    if visualize_url:
        artifact["visualize_url"] = visualize_url
    return artifact


def _slug_filename_part(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(value)).strip("-").lower()
    return slug or "file"


def _safe_extension(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "", value)


def _artifact_download_filename(job: ProcessingJob, artifact_name: str) -> str:
    config_data = _job_config(job)
    domain = _slug_filename_part(str(config_data.get("domain_name") or job.domain or "job"))
    run_id = _slug_filename_part(str(job.job_runs or job.id))
    path_parts = [
        part
        for part in str(artifact_name).replace("\\", "/").split("/")
        if part and part not in {".", ".."}
    ]
    if not path_parts:
        path_parts = ["file"]

    leaf = path_parts[-1]
    stem, extension = os.path.splitext(leaf)
    safe_stem_parts = [_slug_filename_part(part) for part in path_parts[:-1]]
    safe_stem_parts.append(_slug_filename_part(stem or leaf))
    safe_stem = "-".join(part for part in safe_stem_parts if part)
    return f"{domain}-{run_id}-{safe_stem}{_safe_extension(extension)}"


def _download_response_filename(job: ProcessingJob, fallback_artifact_name: str) -> str:
    requested_filename = request.args.get("filename")
    if requested_filename:
        requested_leaf = str(requested_filename).replace("\\", "/").rsplit("/", 1)[-1]
        stem, extension = os.path.splitext(requested_leaf)
        return f"{_slug_filename_part(stem or requested_leaf)}{_safe_extension(extension)}"
    return _artifact_download_filename(job, fallback_artifact_name)


def _visualizer_run_url(job: ProcessingJob) -> str | None:
    if not job.domain:
        return None
    if job.job_runs:
        return f"/visualizer/?run={quote(f'{job.domain}/{job.job_runs}', safe='/')}"

    path_config = _job_path_config(job)
    local_output_dir = _parse_local_path(path_config.get("output_dir"))
    if local_output_dir and (local_output_dir / "graph.json").is_file():
        return f"/visualizer/?run={quote(f'{job.domain}/{job.id}', safe='/')}"
    if (
        job.pipeline == "ontology-harness"
        and local_output_dir
        and (local_output_dir / "ontology.ttl").is_file()
    ):
        return f"/visualizer/?run={quote(f'{job.domain}/{job.id}', safe='/')}"

    return None


def _ontology_download_url(job: ProcessingJob) -> str | None:
    path_config = _job_path_config(job)
    local_output_dir = _parse_local_path(path_config.get("output_dir"))
    if local_output_dir:
        ontology_path = (
            local_output_dir / "ontology.ttl"
            if local_output_dir.is_dir()
            else local_output_dir
        )
        if ontology_path.name == "ontology.ttl" and ontology_path.is_file():
            return _local_file_download_url(
                job.id,
                ontology_path,
                _artifact_download_filename(job, "ontology.ttl"),
            )

    if job.domain and job.job_runs:
        key = f"{job.domain}/{job.job_runs}/output/ontology.ttl"
        return _s3_file_download_url(
            job.id,
            _default_bucket_name(),
            key,
            _artifact_download_filename(job, "ontology.ttl"),
        )

    return None


def _download_label_for_artifact(name: str) -> str:
    return "Download"


def _normalise_prefix(prefix: str) -> str:
    return prefix if prefix.endswith("/") else f"{prefix}/"


def _parse_s3_uri(uri: str | None) -> tuple[str, str] | None:
    if not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        return None
    return parsed.netloc, _normalise_prefix(parsed.path.lstrip("/"))


def _parse_local_path(uri: str | None) -> Path | None:
    if not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme == "s3":
        return None
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).expanduser().resolve()
    if parsed.scheme:
        return None
    return Path(uri).expanduser().resolve()


def _job_config(job: ProcessingJob) -> dict:
    if not job.config_data:
        return {}
    try:
        config_data = json.loads(job.config_data)
    except json.JSONDecodeError:
        return {}
    return config_data if isinstance(config_data, dict) else {}


def _normalise_url_list(value) -> list[str]:
    if not isinstance(value, list):
        return []

    urls = []
    seen = set()
    for item in value:
        url = str(item).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _submitted_domain_links(job: ProcessingJob) -> list[str]:
    return _normalise_url_list(_job_config(job).get("links"))


def _domain_source_urls_from_sidecar(job: ProcessingJob) -> list[str] | None:
    if not job.domain:
        return None

    s3_client = boto3.client("s3")
    try:
        response = s3_client.get_object(
            Bucket=_default_bucket_name(),
            Key=f"{job.domain}/input/sources.json",
        )
        raw_sources = response["Body"].read().decode("utf-8")
        sources = json.loads(raw_sources)
    except Exception as exc:
        current_app.logger.info("No sources sidecar found for domain %s: %s", job.domain, exc)
        return None

    if not isinstance(sources, dict):
        return None
    return _normalise_url_list(list(sources.values()))


def _domain_source_urls(job: ProcessingJob) -> list[str]:
    sidecar_urls = _domain_source_urls_from_sidecar(job)
    if sidecar_urls is not None:
        return sidecar_urls
    return _submitted_domain_links(job)


def _is_protected_review_domain(domain: str | None) -> bool:
    return (domain or "").strip().lower() in PROTECTED_REVIEW_DOMAIN_NAMES


def _list_s3_objects(s3_client, bucket_name: str, prefix: str) -> list[dict]:
    paginator = s3_client.get_paginator("list_objects_v2")
    objects = []
    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
        objects.extend(
            item
            for item in page.get("Contents", [])
            if not str(item.get("Key", "")).endswith("/")
        )
    return objects


def _job_path_config(job: ProcessingJob) -> dict:
    config_data = _job_config(job)
    path_config = config_data.get("path") if isinstance(config_data.get("path"), dict) else {}
    return path_config if isinstance(path_config, dict) else {}


def _output_artifact_group(file_name: str) -> str:
    if file_name in {"graph.json", "ontology.ttl", "schema.json"}:
        return "ontology_files"
    if (
        file_name == "stdout.log"
        or file_name in {"regression_report.json", "owl_ontology_metrics.csv", "bedrock_costs.csv", "export_status.json"}
        or "_report." in file_name
        or "_summary." in file_name
        or "_metrics." in file_name
        or "_costs." in file_name
        or "_status." in file_name
    ):
        return "reports"
    return "intermediary_files"


def _add_folder_artifact(
    groups: dict[str, list[dict]],
    seen_folders: set[tuple[str, str, str]],
    group_name: str,
    job_id: str,
    bucket_name: str,
    prefix: str,
    label: str,
) -> None:
    key = (group_name, bucket_name, prefix)
    if key in seen_folders:
        return
    seen_folders.add(key)
    groups[group_name].append(
        _artifact_row(
            label,
            _folder_download_url(job_id, bucket_name, prefix),
            kind="folder",
        )
    )


def _add_local_folder_artifact(
    groups: dict[str, list[dict]],
    seen_folders: set[tuple[str, str, str]],
    group_name: str,
    job_id: str,
    path: Path,
    label: str,
) -> None:
    key = (group_name, "local", str(path))
    if key in seen_folders:
        return
    seen_folders.add(key)
    groups[group_name].append(
        _artifact_row(
            label,
            _local_folder_download_url(job_id, path),
            kind="folder",
        )
    )


def _add_local_file_artifact(
    groups: dict[str, list[dict]],
    group_name: str,
    job_id: str,
    path: Path,
    label: str,
    job: ProcessingJob,
) -> None:
    groups[group_name].append(
        _artifact_row(
            label,
            _local_file_download_url(job_id, path, _artifact_download_filename(job, label)),
            size=path.stat().st_size,
            download_label=_download_label_for_artifact(label),
        )
    )


def _iter_local_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(file_path for file_path in path.rglob("*") if file_path.is_file())
    return []


def _deduplicate_artifact_groups(groups: dict[str, list[dict]]) -> dict[str, list[dict]]:
    deduplicated: dict[str, list[dict]] = {}
    for group_name, artifacts in groups.items():
        seen_by_name: dict[str, dict] = {}
        deduplicated[group_name] = []
        for artifact in artifacts:
            name = str(artifact.get("name", ""))
            existing = seen_by_name.get(name)
            if existing is not None:
                if "visualize_url" not in existing and artifact.get("visualize_url"):
                    existing["visualize_url"] = artifact["visualize_url"]
                continue

            seen_by_name[name] = artifact
            deduplicated[group_name].append(artifact)
    return deduplicated


def _add_local_input_artifacts(
    groups: dict[str, list[dict]],
    seen_folders: set[tuple[str, str, str]],
    job: ProcessingJob,
    input_path: Path,
) -> None:
    files = _iter_local_files(input_path)
    if not files:
        return

    for file_path in files:
        if input_path.is_dir():
            label = f"input/{file_path.relative_to(input_path).as_posix()}"
        else:
            label = f"input/{file_path.name}"
        _add_local_file_artifact(groups, "intermediary_files", job.id, file_path, label, job)


def _add_local_output_artifacts(
    groups: dict[str, list[dict]],
    seen_folders: set[tuple[str, str, str]],
    job: ProcessingJob,
    output_path: Path,
) -> None:
    files = _iter_local_files(output_path)
    if not files:
        return

    for file_path in files:
        if output_path.is_dir():
            relative_path = file_path.relative_to(output_path)
            label = f"output/{relative_path.as_posix()}"
        else:
            label = f"output/{file_path.name}"
        group_name = _output_artifact_group(file_path.name)
        _add_local_file_artifact(
            groups,
            group_name,
            job.id,
            file_path,
            label,
            job,
        )


def _add_run_artifact(
    groups: dict[str, list[dict]],
    seen_folders: set[tuple[str, str, str]],
    job: ProcessingJob,
    bucket_name: str,
    run_prefix: str,
    item: dict,
) -> None:
    key = str(item["Key"])
    relative_path = key.removeprefix(run_prefix)
    if not relative_path:
        return
    if relative_path == "config.yaml":
        return

    if relative_path.startswith("output/"):
        output_path = relative_path.removeprefix("output/")
        parts = output_path.split("/")
        file_name = parts[-1]
        group_name = _output_artifact_group(file_name)
        groups[group_name].append(
            _artifact_row(
                relative_path,
                _s3_file_download_url(
                    job.id,
                    bucket_name,
                    key,
                    _artifact_download_filename(job, relative_path),
                ),
                size=item.get("Size"),
                download_label=_download_label_for_artifact(file_name),
                visualize_url=_visualizer_run_url(job) if file_name == "graph.json" else None,
            )
        )
        return

    groups["intermediary_files"].append(
        _artifact_row(
            relative_path,
            _s3_file_download_url(
                job.id,
                bucket_name,
                key,
                _artifact_download_filename(job, relative_path),
            ),
            size=item.get("Size"),
        )
    )


def _add_input_artifacts(
    groups: dict[str, list[dict]],
    seen_folders: set[tuple[str, str, str]],
    job: ProcessingJob,
    s3_client,
) -> None:
    path_config = _job_path_config(job)
    input_location = _parse_s3_uri(path_config.get("input_path"))
    if not input_location:
        return

    bucket_name, input_prefix = input_location
    items = _list_s3_objects(s3_client, bucket_name, input_prefix)
    for item in items:
        key = str(item["Key"])
        relative_path = key.removeprefix(input_prefix)
        if not relative_path:
            continue
        label = f"input/{relative_path}"
        groups["intermediary_files"].append(
            _artifact_row(
                label,
                _s3_file_download_url(
                    job.id,
                    bucket_name,
                    key,
                    _artifact_download_filename(job, label),
                ),
                size=item.get("Size"),
            )
        )

def _job_artifact_groups(job: ProcessingJob) -> dict[str, list[dict]]:
    groups = {"ontology_files": [], "intermediary_files": [], "reports": []}
    seen_folders: set[tuple[str, str, str]] = set()
    path_config = _job_path_config(job)

    if job.config_data:
        groups["intermediary_files"].append(
            _artifact_row(
                "config.yaml",
                (
                    f"/ontology/jobs/{quote(job.id)}/downloads/config.yaml"
                    f"?filename={quote(_artifact_download_filename(job, 'config.yaml'), safe='')}"
                ),
            )
        )
    if job.domain_prompt is not None:
        groups["intermediary_files"].append(
            _artifact_row(
                "prompts.txt",
                (
                    f"/ontology/jobs/{quote(job.id)}/downloads/prompts.txt"
                    f"?filename={quote(_artifact_download_filename(job, 'prompts.txt'), safe='')}"
                ),
            )
        )

    local_input_path = _parse_local_path(path_config.get("input_path"))
    if local_input_path:
        _add_local_input_artifacts(groups, seen_folders, job, local_input_path)

    local_output_path = _parse_local_path(path_config.get("output_dir"))
    if local_output_path:
        _add_local_output_artifacts(groups, seen_folders, job, local_output_path)

    if job.domain and job.job_runs:
        s3_client = boto3.client("s3")
        bucket_name = _default_bucket_name()
        run_prefix = _normalise_prefix(f"{job.domain}/{job.job_runs}")
        items = _list_s3_objects(s3_client, bucket_name, run_prefix)
        for item in items:
            _add_run_artifact(groups, seen_folders, job, bucket_name, run_prefix, item)
        _add_input_artifacts(groups, seen_folders, job, s3_client)

    return _deduplicate_artifact_groups(groups)


def _allowed_download_prefixes(job: ProcessingJob) -> set[tuple[str, str]]:
    allowed: set[tuple[str, str]] = set()
    if job.domain and job.job_runs:
        allowed.add((_default_bucket_name(), _normalise_prefix(f"{job.domain}/{job.job_runs}")))

    path_config = _job_path_config(job)
    input_location = _parse_s3_uri(path_config.get("input_path"))
    if input_location:
        allowed.add(input_location)
    return allowed


def _allowed_local_paths(job: ProcessingJob) -> set[Path]:
    allowed: set[Path] = set()
    path_config = _job_path_config(job)
    for path_name in ("input_path", "output_dir"):
        local_path = _parse_local_path(path_config.get(path_name))
        if local_path:
            allowed.add(local_path)
    return allowed


def _is_allowed_local_path(job: ProcessingJob, requested_path: Path) -> bool:
    for allowed_path in _allowed_local_paths(job):
        if requested_path == allowed_path or requested_path.is_relative_to(allowed_path):
            return True
    return False


def _apply_selected_domain_to_config(config_data: dict, selected_domain: str | None) -> dict:
    """Apply the UI-selected domain and its default S3 paths to uploaded config."""
    if not selected_domain or selected_domain == "config_file":
        return config_data

    domain = str(selected_domain)
    config_data["domain_name"] = domain

    filesystem = config_data.get("filesystem") or {}
    if filesystem.get("protocol") == "s3":
        bucket_name = os.getenv("S3_BUCKET_NAME", DEFAULT_S3_BUCKET)
        path = config_data.setdefault("path", {})
        path["input_path"] = f"s3://{bucket_name}/{domain}/input"
        path["output_dir"] = f"s3://{bucket_name}/{domain}"
        config_data.pop("input_path", None)
        config_data.pop("output_dir", None)

    return config_data


def _load_default_config_template() -> dict:
    """Load the downloadable source configuration template as the default run config."""
    with DEFAULT_CONFIG_TEMPLATE_PATH.open(encoding="utf-8") as template_file:
        config_data = yaml.safe_load(template_file) or {}
    if not isinstance(config_data, dict):
        raise ValueError("Default source configuration template must contain a YAML mapping.")
    return config_data


def create_blueprints():
    """Create and register blueprints."""
    healthcheck_bp = Blueprint('healthcheck', __name__, url_prefix=BLUEPRINTS['healthcheck']['prefix'])
    ontology_bp = Blueprint('ontology', __name__, url_prefix=BLUEPRINTS['ontology']['prefix'])
    viewer_bp = Blueprint('viewer', __name__, url_prefix='/viewer')
    home_bp = Blueprint('home', __name__, url_prefix='/')

    @home_bp.route("/")
    def home():
        return redirect('/ontology')

    @healthcheck_bp.route("/ready")
    def health_check():
        return {"status": "healthy", "message": "Application is ready"}, 200

    @ontology_bp.route("/", methods=['GET'])
    def index():
        try:
            default_config = _load_default_config_template()
        except Exception as e:
            current_app.logger.error("Failed to load default config template: %s", e)
            default_config = {}
        return render_template('dashboard.html', active_page='dashboard', default_config=default_config)

    @ontology_bp.route('/test_data')
    def test_data():
        try:
            job = ProcessingJob(id=12, status="pending", domain="test")
            db.session.add(job)
            db.session.commit()
        except OperationalError as oe:
            from flask import current_app
            current_app.logger.warning("Database unavailable, proceeding without job tracking: %s", oe)
        return render_template('dashboard.html', active_page='dashboard')

    @ontology_bp.route('/submit', methods=['POST'])
    def upload_file():
        config_json = request.form.get('config_json')
        yaml_file = request.files.get('file')
        has_config_file = bool(yaml_file and yaml_file.filename)
        if not config_json and has_config_file and not is_yaml_file(yaml_file.filename):
            return error_response("Invalid YAML file. Please upload a .yaml or .yml file.")

        domain_prompt = DEFAULT_DOMAIN_PROMPT
        domain_prompt_file = request.files.get('text_file')

        try:
            if config_json:
                config_data = json.loads(config_json)
            elif has_config_file:
                config_data = yaml.safe_load(yaml_file)
            else:
                config_data = _load_default_config_template()

            if not isinstance(config_data, dict):
                return error_response("Configuration file must contain a YAML mapping.", 400)

            config_data = _apply_selected_domain_to_config(
                config_data,
                request.form.get('domain'),
            )

            if domain_prompt_file and domain_prompt_file.filename:
                domain_prompt = domain_prompt_file.read().decode('utf-8')

            job_id = str(uuid4())

            tracking = True
            try:
                job = ProcessingJob(
                    id=job_id,
                    status="pending",
                    domain=config_data.get('domain_name'),
                    config_data=json.dumps(config_data),
                    domain_prompt=domain_prompt,
                )
                db.session.add(job)
                db.session.commit()
            except OperationalError as oe:
                current_app.logger.warning("Database unavailable, proceeding without job tracking: %s", oe)
                tracking = False

            response_payload = {"job_id": job_id, "status": "pending"}
            if not tracking:
                response_payload["warning"] = "database unavailable; status cannot be tracked"

            return jsonify(response_payload), 202

        except yaml.YAMLError as e:
            return error_response(f"Invalid YAML format: {str(e)}", 400)
        except Exception as e:
            return error_response(f"Job submission failed: {str(e)}", 500)

    @ontology_bp.route('/domains', methods=['GET'])
    def domains_page():
        """Render the Domains menu page so IAs can launch an ingestion run."""
        return render_template('domains.html', active_page='domains')

    @ontology_bp.route('/review-domains', methods=['GET'])
    def review_domains():
        return render_template(
            'review_domains.html',
            active_page='review-domains',
            include_materialize=False,
        )

    @ontology_bp.route('/domains/review', methods=['GET'])
    def review_domain_jobs():
        page = max(request.args.get("page", default=1, type=int) or 1, 1)
        per_page = request.args.get("per_page", default=10, type=int) or 10
        per_page = min(max(per_page, 1), 50)
        search = (request.args.get("search") or "").strip().lower()
        sort_key = request.args.get("sort", "created_at")
        sort_direction = request.args.get("direction", "desc")

        ingestion_jobs = (
            db.session.query(ProcessingJob)
            .filter(
                ProcessingJob.pipeline == "ingestion",
                ProcessingJob.domain.isnot(None),
            )
            .order_by(ProcessingJob.domain.asc(), ProcessingJob.created_at.desc(), ProcessingJob.id.asc())
            .all()
        )

        latest_by_domain: dict[str, ProcessingJob] = {}
        for job in ingestion_jobs:
            domain = (job.domain or "").strip()
            if (
                domain
                and not _is_protected_review_domain(domain)
                and domain not in latest_by_domain
            ):
                latest_by_domain[domain] = job

        domain_jobs = list(latest_by_domain.values())
        note_metadata = _note_metadata_for_jobs([job.id for job in domain_jobs])

        if search:
            def matches_search(job: ProcessingJob) -> bool:
                latest_note = note_metadata.get(job.id, {}).get("latest_note") or {}
                values = [
                    job.id,
                    job.domain,
                    job.status,
                    job.error_message,
                    latest_note.get("text"),
                ]
                return any(search in str(value or "").lower() for value in values)

            domain_jobs = [job for job in domain_jobs if matches_search(job)]

        def sort_value(job: ProcessingJob):
            if sort_key == "domain":
                return ((job.domain or "").lower(), job.id)
            if sort_key == "status":
                return ((job.status or "").lower(), job.id)
            if sort_key == "notes":
                return (note_metadata.get(job.id, {}).get("notes_count", 0), job.id)
            return (job.created_at or datetime.min.replace(tzinfo=timezone.utc), job.id)

        domain_jobs = sorted(
            domain_jobs,
            key=sort_value,
            reverse=sort_direction != "asc",
        )

        total_items = len(domain_jobs)
        total_pages = (total_items + per_page - 1) // per_page if total_items else 0
        start = (page - 1) * per_page
        selected_jobs = domain_jobs[start:start + per_page]

        return jsonify(
            {
                "domains": [
                    _serialize_domain_job(job, note_metadata)
                    for job in selected_jobs
                ],
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total_items": total_items,
                    "total_pages": total_pages,
                    "has_next": page < total_pages,
                    "has_previous": page > 1 and total_pages > 0,
                },
            }
        )

    @ontology_bp.route('/domains/review/<job_id>/urls', methods=['GET'])
    def review_domain_urls(job_id):
        job = db.session.get(ProcessingJob, job_id)
        if job is None or job.pipeline != "ingestion":
            return error_response("Domain not found", 404)
        return jsonify({"job_id": job.id, "domain": job.domain, "urls": _domain_source_urls(job)})

    @ontology_bp.route('/ingest', methods=['POST'])
    def ingest_content():
        """Trigger the ingestion pipeline for the given domain and URL list."""
        job_id = str(uuid4())
        domain = None
        config_content = None
        links_list = None
        source_job_id = None

        if request.is_json:
            data = request.get_json() or {}
            domain = (data.get('domain') or '').strip() or None
            config_content = data.get('config_content')
            links_list = _normalise_url_list(data.get('links'))
            source_job_id = (data.get('source_job_id') or '').strip() or None

        if not domain:
            return error_response("Domain is required.")
        if not links_list:
            return error_response("A URL list with at least one URL is required.")

        bucket_name = os.getenv('S3_BUCKET_NAME', DEFAULT_S3_BUCKET)
        try:
            create_bucket_folder(bucket_name, domain)
        except Exception as s3_err:
            current_app.logger.warning("Could not ensure S3 folder for domain %s: %s", domain, s3_err)

        tracking = True
        try:
            notes_to_copy = []
            source_job = db.session.get(ProcessingJob, source_job_id) if source_job_id else None
            if (
                source_job is not None
                and source_job.pipeline == "ingestion"
                and source_job.domain == domain
            ):
                notes_to_copy = [
                    (note.text, note.created_at, note.updated_at)
                    for note in _notes_for_job(source_job)
                ]

            job = ProcessingJob(
                id=job_id,
                status="pending",
                pipeline="ingestion",
                domain=domain,
                config_data=json.dumps(
                    {
                        "links": links_list,
                        "config_content": config_content,
                    }
                ),
            )
            db.session.add(job)
            for note_text, created_at, updated_at in notes_to_copy:
                db.session.add(
                    ProcessingJobNote(
                        job_id=job.id,
                        text=note_text,
                        created_at=created_at,
                        updated_at=updated_at,
                    )
                )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.warning("Database unavailable, proceeding without job tracking: %s", e)
            tracking = False

        executor.submit(
            run_ingestion_background_task,
            config_path=None,
            config_content=config_content,
            links_list=links_list,
            job_id=job_id,
            domain=domain,
        )

        response_payload = {"job_id": job_id, "status": "pending"}
        if not tracking:
            response_payload["warning"] = "database unavailable; status cannot be tracked"

        return jsonify(response_payload), 202

    @ontology_bp.route('/ingest/status/<job_id>', methods=['GET'])
    def ingest_job_status(job_id):
        """Return the status of a previously submitted ingestion job."""
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Ingestion job not found", 404)
        return jsonify({"job_id": job.id, "status": job.status, "error": job.error_message, "created_at": _serialize_job_datetime(job.created_at)})

    @ontology_bp.route('/status/<job_id>', methods=['GET'])
    def job_status(job_id):
        """Return the status of a previously submitted job."""
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Job not found", 404)
        return jsonify({"job_id": job.id, "pipeline": job.pipeline, "domain": job.domain, "status": job.status, "job_runs": job.job_runs, "error": job.error_message})

    @ontology_bp.route('/jobs', methods=['GET'])
    def list_jobs():
        today_start = datetime(2026, 3, 13, tzinfo=timezone.utc)

        limit = request.args.get('limit', type=int)

        query = (
            db.session.query(ProcessingJob)
            .filter(ProcessingJob.created_at >= today_start)
        )
        query = query.order_by(ProcessingJob.created_at.desc())

        if limit:
            query = query.limit(limit)

        jobs = query.all()
        note_metadata = _note_metadata_for_jobs([job.id for job in jobs])
        job_list = [_serialize_job(job, note_metadata) for job in jobs]
        return jsonify(job_list)

    @ontology_bp.route('/jobs/review', methods=['GET'])
    def review_jobs():
        today_start = datetime(2026, 3, 13, tzinfo=timezone.utc)
        job_type = request.args.get("type", "ontology")
        page = max(request.args.get("page", default=1, type=int) or 1, 1)
        per_page = request.args.get("per_page", default=10, type=int) or 10
        per_page = min(max(per_page, 1), 50)
        search = (request.args.get("search") or "").strip()
        sort_key = request.args.get("sort", "created_at")
        sort_direction = request.args.get("direction", "desc")

        query = db.session.query(ProcessingJob).filter(ProcessingJob.created_at >= today_start)
        if job_type == "test":
            query = query.filter(ProcessingJob.pipeline == "ontology-harness")
        else:
            query = query.filter(
                or_(
                    ProcessingJob.pipeline.is_(None),
                    ProcessingJob.pipeline == "ontology",
                )
            )

        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    ProcessingJob.id.ilike(search_term),
                    ProcessingJob.job_runs.ilike(search_term),
                    ProcessingJob.domain.ilike(search_term),
                    ProcessingJob.status.ilike(search_term),
                    ProcessingJob.pipeline.ilike(search_term),
                )
            )

        sort_expressions = {
            "ontology": func.coalesce(ProcessingJob.job_runs, ProcessingJob.id),
            "domain": ProcessingJob.domain,
            "created_at": ProcessingJob.created_at,
            "status": ProcessingJob.status,
            "type": ProcessingJob.pipeline,
        }
        sort_expression = sort_expressions.get(sort_key, ProcessingJob.created_at)
        order_expression = (
            sort_expression.asc()
            if sort_direction == "asc"
            else sort_expression.desc()
        )

        total_items = query.count()
        jobs = (
            query.order_by(order_expression, ProcessingJob.id.asc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        total_pages = (total_items + per_page - 1) // per_page if total_items else 0
        note_metadata = _note_metadata_for_jobs([job.id for job in jobs])

        return jsonify(
            {
                "jobs": [_serialize_job(job, note_metadata) for job in jobs],
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total_items": total_items,
                    "total_pages": total_pages,
                    "has_next": page < total_pages,
                    "has_previous": page > 1 and total_pages > 0,
                },
            }
        )

    @ontology_bp.route('/jobs/<job_id>/stop', methods=['POST'])
    def stop_job(job_id):
        """Manually stop a pending or running job and clear its worker lease."""
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Job not found", 404)

        if job.status not in {"pending", "running"}:
            return error_response(f"Cannot stop job with status '{job.status}'", 409)

        job.status = "stopped"
        job.error_message = "Manually stopped from Jobs UI"
        job.claimed_by = None
        job.claimed_at = None
        job.heartbeat_at = None
        db.session.commit()

        return jsonify({"job_id": job.id, "status": job.status, "error": job.error_message})

    @ontology_bp.route('/jobs/<job_id>/notes', methods=['GET'])
    def get_job_notes(job_id):
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Job not found", 404)

        return jsonify([_serialize_job_note(note) for note in _notes_for_job(job)])

    @ontology_bp.route('/jobs/<job_id>/notes', methods=['POST'])
    def save_job_notes(job_id):
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Job not found", 404)

        payload = request.get_json(silent=True)
        if isinstance(payload, list):
            db.session.query(ProcessingJobNote).filter(
                ProcessingJobNote.job_id == job.id
            ).delete()
            for note_payload in payload:
                text = _note_text_from_payload(note_payload)
                if not text:
                    continue
                created_at = _parse_note_datetime(
                    note_payload.get("created_at") or note_payload.get("timestamp")
                )
                db.session.add(
                    ProcessingJobNote(
                        job_id=job.id,
                        text=text,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
            db.session.commit()
            return jsonify(
                {
                    "status": "success",
                    "notes": [_serialize_job_note(note) for note in _notes_for_job(job)],
                }
            )

        text = _note_text_from_payload(payload)
        if not text:
            return error_response("Note text is required", 400)

        note = ProcessingJobNote(job_id=job.id, text=text)
        db.session.add(note)
        db.session.commit()
        return jsonify(_serialize_job_note(note)), 201

    @ontology_bp.route('/jobs/<job_id>/notes/<int:note_id>', methods=['PATCH'])
    def update_job_note(job_id, note_id):
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Job not found", 404)

        note = db.session.get(ProcessingJobNote, note_id)
        if note is None or note.job_id != job.id:
            return error_response("Note not found", 404)

        text = _note_text_from_payload(request.get_json(silent=True))
        if not text:
            return error_response("Note text is required", 400)

        note.text = text
        note.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify(_serialize_job_note(note))

    @ontology_bp.route('/jobs/<job_id>/notes/<int:note_id>', methods=['DELETE'])
    def delete_job_note(job_id, note_id):
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Job not found", 404)

        note = db.session.get(ProcessingJobNote, note_id)
        if note is None or note.job_id != job.id:
            return error_response("Note not found", 404)

        db.session.delete(note)
        db.session.commit()
        return Response(status=204)

    @ontology_bp.route('/jobs/<job_id>/artifacts', methods=['GET'])
    def job_artifacts(job_id):
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Job not found", 404)
        try:
            groups = _job_artifact_groups(job)
        except Exception as exc:
            current_app.logger.warning(
                "Unable to load artifacts for job %s: %s", job.id, exc
            )
            return error_response("Unable to load job details.", 502)
        return jsonify({"job_id": job.id, "groups": groups})

    @ontology_bp.route('/jobs/<job_id>/downloads/local-file', methods=['GET'])
    def download_job_local_file(job_id):
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Job not found", 404)

        requested_path = Path(unquote(request.args.get("path") or "")).expanduser().resolve()
        if not _is_allowed_local_path(job, requested_path):
            return error_response("File is not available for this job", 403)
        if not requested_path.is_file():
            return error_response("File not found", 404)

        return Response(
            requested_path.read_bytes(),
            mimetype="application/octet-stream",
            headers={
                "Content-Disposition": (
                    f"attachment; filename={_download_response_filename(job, requested_path.name)}"
                )
            },
        )

    @ontology_bp.route('/jobs/<job_id>/downloads/s3-file', methods=['GET'])
    def download_job_s3_file(job_id):
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Job not found", 404)

        bucket_name = request.args.get("bucket") or ""
        key = request.args.get("key") or ""
        allowed = _allowed_download_prefixes(job)
        if not any(bucket_name == bucket and key.startswith(allowed_prefix) for bucket, allowed_prefix in allowed):
            return error_response("File is not available for this job", 403)

        s3_client = boto3.client("s3")
        try:
            response = s3_client.get_object(Bucket=bucket_name, Key=key)
        except Exception:
            return error_response("File not found", 404)

        fallback_name = key.rsplit("/", 1)[-1] or "file"
        return Response(
            response["Body"].read(),
            mimetype="application/octet-stream",
            headers={
                "Content-Disposition": (
                    f"attachment; filename={_download_response_filename(job, fallback_name)}"
                )
            },
        )

    @ontology_bp.route('/jobs/<job_id>/downloads/local-folder', methods=['GET'])
    def download_job_local_folder(job_id):
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Job not found", 404)

        requested_path = Path(unquote(request.args.get("path") or "")).expanduser().resolve()
        if not _is_allowed_local_path(job, requested_path):
            return error_response("Folder is not available for this job", 403)
        if not requested_path.is_dir():
            return error_response("Folder not found", 404)

        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(path for path in requested_path.rglob("*") if path.is_file()):
                archive.write(file_path, file_path.relative_to(requested_path).as_posix())

        return Response(
            archive_bytes.getvalue(),
            mimetype="application/zip",
            headers={"Content-Disposition": f"attachment; filename={requested_path.name}.zip"},
        )

    @ontology_bp.route('/jobs/<job_id>/downloads/<path:artifact_name>', methods=['GET'])
    def download_job_virtual_artifact(job_id, artifact_name):
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Job not found", 404)

        if artifact_name == "config.yaml":
            body = yaml.safe_dump(_job_config(job), sort_keys=False)
            return Response(
                body,
                mimetype="application/x-yaml",
                headers={
                    "Content-Disposition": (
                        f"attachment; filename={_download_response_filename(job, 'config.yaml')}"
                    )
                },
            )

        if artifact_name in {"prompt.txt", "prompts.txt"}:
            return Response(
                job.domain_prompt or "",
                mimetype="text/plain",
                headers={
                    "Content-Disposition": (
                        f"attachment; filename={_download_response_filename(job, 'prompts.txt')}"
                    )
                },
            )

        return error_response("Artifact not found", 404)

    @ontology_bp.route('/jobs/<job_id>/downloads/folder', methods=['GET'])
    def download_job_folder(job_id):
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Job not found", 404)

        bucket_name = request.args.get("bucket") or ""
        prefix = request.args.get("prefix") or ""
        allowed = _allowed_download_prefixes(job)
        if not any(bucket_name == bucket and prefix.startswith(allowed_prefix) for bucket, allowed_prefix in allowed):
            return error_response("Folder is not available for this job", 403)

        s3_client = boto3.client("s3")
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in _list_s3_objects(s3_client, bucket_name, prefix):
                key = str(item["Key"])
                response = s3_client.get_object(Bucket=bucket_name, Key=key)
                archive_name = key.removeprefix(prefix) or key.rsplit("/", 1)[-1]
                archive.writestr(archive_name, response["Body"].read())

        folder_name = prefix.rstrip("/").rsplit("/", 1)[-1] or "files"
        return Response(
            archive_bytes.getvalue(),
            mimetype="application/zip",
            headers={"Content-Disposition": f"attachment; filename={folder_name}.zip"},
        )

    @ontology_bp.route('/review-ontologies', methods=['GET'])
    def review_ontologies():
        return render_template(
            'jobs.html',
            active_page='jobs',
            review_job_type='ontology',
            review_page_title='Review Ontologies',
            review_page_description='View your available ontologies below. Click any row to see more information about it.',
            include_materialize=False,
        )

    @ontology_bp.route('/review-tests', methods=['GET'])
    def review_tests():
        return render_template(
            'jobs.html',
            active_page='tests',
            review_job_type='test',
            review_page_title='Review Tests',
            review_page_description='View ontology harness test runs, regression reports, and review notes.',
            include_materialize=False,
        )

    @ontology_bp.route('/all_jobs', methods=['GET'])
    def all_jobs():
        return redirect('/ontology/review-ontologies')

    @ontology_bp.route("/list_domains")
    def list_domains():
        return get_domain_list('govuk-ai-accelerator-data-integration')

    @viewer_bp.route("/bucket/download/buckets/<bucket_name>/<path:path>")
    def download_file(bucket_name: str, path: str) -> Response:
        s3_client = boto3.client("s3")
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": path},
            ExpiresIn=3600,
        )

        return redirect(url)

    return healthcheck_bp, ontology_bp, viewer_bp, home_bp


_cached_app = None


def create_flask_app():
    global _cached_app
    configure_logging()
    if _cached_app:
        return _cached_app

    app = Flask(__name__)

    database_uri = os.getenv("DATABASE_URL")
    allow_in_memory_db = os.getenv("ALLOW_IN_MEMORY_DB", "").lower() == "true"
    disable_task_manager = os.getenv("DISABLE_TASK_MANAGER", "").lower() == "true"

    if database_uri:
        app.config["SQLALCHEMY_DATABASE_URI"] = database_uri
    elif allow_in_memory_db:
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    else:
        raise RuntimeError(
            "DATABASE_URL must be set for durable job processing. "
            "Set ALLOW_IN_MEMORY_DB=true only for local development."
        )

    db.init_app(app)
    migrate.init_app(app, db)

    healthcheck_bp, ontology_bp, viewer_bp, home_bp = create_blueprints()
    app.register_blueprint(healthcheck_bp)
    app.register_blueprint(ontology_bp)
    app.register_blueprint(viewer_bp)
    app.register_blueprint(home_bp)

    govuk_assets = Blueprint(
        "govuk_assets",
        __name__,
        static_folder="static/vendor/govuk-frontend/assets",
        static_url_path="/assets",
    )
    app.register_blueprint(govuk_assets)

    @app.after_request
    def set_fingerprinted_asset_cache_headers(response):
        if request.endpoint == "govuk_assets.static":
            response.headers["Cache-Control"] = FINGERPRINTED_ASSET_CACHE_CONTROL
        return response

    with app.app_context():
        try:
            migrations_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")
            if os.path.exists(migrations_dir):
                upgrade()
            else:
                db.create_all()
        except Exception as exc:
            if isinstance(exc, OperationalError):
                app.logger.warning("Could not initialize database: %s. Proceeding without database.", exc)
            else:
                raise

    schedule_ontology_harness(app)
    if not disable_task_manager:
        start_task_manager(app)

    _cached_app = app
    return app


async def redirect_visualizer_root(request: Request) -> RedirectResponse:
    target = f"{request.url.path}/"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(url=target)


async def visualizer_unavailable(request: Request) -> HTMLResponse:
    _ = request
    detail = "Install taxonomy_ontology_accelerator to enable the visualizer."
    if VISUALIZER_IMPORT_ERROR is not None:
        detail = f"{detail} Missing dependency: {VISUALIZER_IMPORT_ERROR}."
    return HTMLResponse(
        (
            "<!DOCTYPE html><html><head><title>Visualizer unavailable</title></head>"
            "<body><h1>Visualizer is unavailable</h1>"
            f"<p>{detail}</p></body></html>"
        ),
        status_code=503,
    )


def create_visualizer_asgi_app():
    if visualizer_app is not None:
        return visualizer_app.app
    return Starlette(routes=[
        Route("/", visualizer_unavailable),
        Route("/{path:path}", visualizer_unavailable),
    ])


def create_asgi_app():
    flask_app = create_flask_app()
    return Starlette(routes=[
        Route("/visualizer", redirect_visualizer_root),
        Mount("/visualizer", create_visualizer_asgi_app()),
        Mount("/", WSGIMiddleware(flask_app)),
    ])


def create_app():
    return ASGIMiddleware(create_asgi_app())


if __name__ == '__main__':
    uvicorn.run(create_asgi_app(), host=APP_HOST, port=APP_PORT)
