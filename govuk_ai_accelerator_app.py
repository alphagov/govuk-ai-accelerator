"""GOV.UK AI Accelerator Flask Application."""

import os
import json
import uvicorn
import yaml
import boto3
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, Blueprint, Response, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate, upgrade
from sqlalchemy import DateTime, Integer, String
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
from src.web_browser import routing
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
DEFAULT_CONFIG_TEMPLATE_PATH = (
    Path(__file__).resolve().parent
    / "static"
    / "assets"
    / "templates"
    / "config-template.yaml"
)


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


def _serialize_job_datetime(value: datetime | None) -> str | None:
    """Return job datetimes as explicit UTC instants for browser parsing."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


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

    @ontology_bp.route('/ingest', methods=['POST'])
    def ingest_content():
        """Trigger the ingestion pipeline for the given domain and URL list."""
        job_id = str(uuid4())
        domain = None
        config_content = None
        links_list = None

        if request.is_json:
            data = request.get_json() or {}
            domain = (data.get('domain') or '').strip() or None
            config_content = data.get('config_content')
            links_list = data.get('links')

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
            job = ProcessingJob(id=job_id, status="pending", pipeline="ingestion", domain=domain)
            db.session.add(job)
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
        job_list = [
            {
                "job_id": job.id,
                "pipeline": job.pipeline,
                "domain": job.domain,
                "status": job.status,
                "job_runs": job.job_runs,
                "error": job.error_message,
                "created_at": _serialize_job_datetime(job.created_at),
            }
            for job in jobs
        ]
        return jsonify(job_list)

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

        bucket_name = 'govuk-ai-accelerator-data-integration'
        if job.job_runs and job.domain:
            key = f"{job.domain}/{job.job_runs}/notes.json"
        elif job.domain:
            key = f"{job.domain}/pending-notes/{job.id}.json"
        else:
            return jsonify([])

        s3_client = boto3.client("s3")
        try:
            response = s3_client.get_object(Bucket=bucket_name, Key=key)
            notes_data = response['Body'].read().decode('utf-8')
            return Response(notes_data, mimetype='application/json')
        except s3_client.exceptions.NoSuchKey:
            return jsonify([])
        except Exception as e:
            current_app.logger.error("Error reading notes from S3: %s", e)
            return jsonify([])

    @ontology_bp.route('/jobs/<job_id>/notes', methods=['POST'])
    def save_job_notes(job_id):
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Job not found", 404)

        bucket_name = 'govuk-ai-accelerator-data-integration'
        if job.job_runs and job.domain:
            key = f"{job.domain}/{job.job_runs}/notes.json"
        elif job.domain:
            key = f"{job.domain}/pending-notes/{job.id}.json"
        else:
            return error_response("Domain not specified for job", 400)

        notes_json = request.get_data(as_text=True)
        try:
            json.loads(notes_json)
        except json.JSONDecodeError:
            return error_response("Invalid JSON payload", 400)

        s3_client = boto3.client("s3")
        try:
            s3_client.put_object(
                Bucket=bucket_name,
                Key=key,
                Body=notes_json.encode('utf-8'),
                ContentType='application/json'
            )
            return jsonify({"status": "success", "key": key})
        except Exception as e:
            current_app.logger.error("Error saving notes to S3: %s", e)
            return error_response(f"Failed to save notes to S3: {str(e)}", 500)

    @ontology_bp.route('/all_jobs', methods=['GET'])
    def all_jobs():
        return render_template('jobs.html', active_page='jobs')

    @ontology_bp.route("/list_domains")
    def list_domains():
        return get_domain_list('govuk-ai-accelerator-data-integration')

    @viewer_bp.route("/bucket")
    def viewer_load():
        return routing.index()

    @viewer_bp.route("/bucket/<bucket_name>", defaults={"path": ""})
    @viewer_bp.route("/bucket/<bucket_name>/<path:path>")
    def view_bucket(bucket_name: str, path: str) -> str:
        return routing.view_bucket(bucket_name, path, 1)

    @viewer_bp.route("/api/bucket/<bucket_name>/tree")
    def api_bucket_tree(bucket_name: str):
        prefix = request.args.get('prefix', '')
        return jsonify(routing.get_bucket_tree_nodes(bucket_name, prefix))

    @viewer_bp.route("/bucket/download/buckets/<bucket_name>/<path:path>")
    def download_file(bucket_name: str, path: str) -> Response:
        s3_client = boto3.client("s3")
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": path},
            ExpiresIn=3600,
        )

        return redirect(url)

    @viewer_bp.route("/api/bucket/<bucket_name>/<path:path>", methods=['DELETE'])
    def delete_bucket_object(bucket_name: str, path: str):
        try:
            s3 = boto3.resource("s3")
            bucket = s3.Bucket(bucket_name)

            if path.endswith('/'):
                responses = bucket.objects.filter(Prefix=path).delete()

                errors = []
                for response in responses:
                    if 'Errors' in response:
                        errors.extend(response['Errors'])

                if errors:
                    error_messages = ", ".join([f"{e.get('Key')}: {e.get('Message')}" for e in errors])
                    return jsonify({"error": f"Failed to delete some objects: {error_messages}"}), 500
            else:
                s3.Object(bucket_name, path).delete()
                print(path, bucket, bucket.objects.filter(Prefix=path))

            return jsonify({"message": f"Successfully deleted {path} from {bucket_name}"}), 200
        except Exception as e:
            return jsonify({"error": f"Failed to delete object: {str(e)}"}), 500

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
