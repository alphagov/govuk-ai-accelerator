"""GOV.UK AI Accelerator Flask Application."""

import os

import uvicorn
import yaml
import boto3
from uuid import uuid4
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, Blueprint, Response, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate, upgrade
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.exc import OperationalError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from scripts.pipeline.ontology_generator import run_ontology_background_task
from scripts.pipeline.utils import error_response, is_yaml_file, executor
from scripts.pipeline.constants import APP_HOST, APP_PORT, BLUEPRINTS
from src.web_browser import routing

from starlette.routing import Mount, Route
from a2wsgi import ASGIMiddleware, WSGIMiddleware

try:
    from taxonomy_ontology_accelerator.web import app as visualizer_app
    VISUALIZER_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    visualizer_app = None
    VISUALIZER_IMPORT_ERROR = exc

# Initialize database extension without app binding
db = SQLAlchemy()
migrate = Migrate()


class ProcessingJob(db.Model):
    """Model to track the status of submitted jobs."""

    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String)
    domain: Mapped[str] = mapped_column(String, nullable=True)
    job_runs: Mapped[str] = mapped_column(String, nullable=True)
    error_message: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

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
        return render_template('dashboard.html', active_page='dashboard')

    @ontology_bp.route('/submit', methods=['POST'])
    def upload_file():
        if 'file' not in request.files:
            return error_response("Configuration file is missing")
        
        yaml_file = request.files['file']
        
        if not yaml_file.filename or not is_yaml_file(yaml_file.filename):
            return error_response("Invalid YAML file. Please upload a .yaml or .yml file.")
        
        domain_prompt = None
        domain_prompt_file = request.files.get('text_file')
        
        try:
            config_data = yaml.safe_load(yaml_file)

            if domain_prompt_file and domain_prompt_file.filename:
                domain_prompt = domain_prompt_file.read().decode('utf-8')

            job_id = str(uuid4())

          
            tracking = True
            try:
                job = ProcessingJob(id=job_id, status="pending", domain=config_data.get('domain_name'))
                db.session.add(job)
                db.session.commit()
            except OperationalError as oe:
                from flask import current_app
                current_app.logger.warning("Database unavailable, proceeding without job tracking: %s", oe)
                tracking = False

            executor.submit(
                run_ontology_background_task,
                config_data,
                domain_prompt,
                job_id if tracking else None,
            )

            response_payload = {"job_id": job_id, "status": "pending"}
            if not tracking:
                response_payload["warning"] = "database unavailable; status cannot be tracked"

            return jsonify(response_payload), 202

        except yaml.YAMLError as e:
            return error_response(f"Invalid YAML format: {str(e)}", 400)
        except Exception as e:
            return error_response(f"Job submission failed: {str(e)}", 500)

    @ontology_bp.route('/status/<job_id>', methods=['GET'])
    def job_status(job_id):
        """Return the status of a previously submitted job."""
        job = db.session.get(ProcessingJob, job_id)
        if job is None:
            return error_response("Job not found", 404)
        return jsonify({"job_id": job.id, "Domain": job.domain, "status": job.status, "job_runs": job.job_runs, "error": job.error_message})

    @ontology_bp.route('/jobs', methods=['GET'])
    def list_jobs():
        """Return a list of all jobs."""
        jobs = db.session.query(ProcessingJob).order_by(ProcessingJob.created_at.desc()).limit(5).all()
        job_list = []
        for job in jobs:
            job_list.append({
                "job_id": job.id,
                "domain": job.domain,
                "status": job.status,
                "job_runs": job.job_runs,
                "error": job.error_message,
                "created_at": job.created_at.isoformat() if job.created_at else None
            })
        return jsonify(job_list)

    @ontology_bp.route('/opensearch/<domain_name>/status', methods=['GET'])
    def open_search_status(domain_name):
        """Return the status of a previously submitted job."""
        client = boto3.client('opensearch', region_name='eu-west-1')

        response = client.describe_domain(DomainName=domain_name)
        status = response['DomainStatus']['Processing']
        return jsonify({"status": f"Processing Status: {'Still Building' if status else 'Active'}",
                        'domain_name': response['DomainStatus']['DomainName']})


    @viewer_bp.route("/bucket")
    def viewer_load():
        return routing.index() # Active page logic needs to be handled in routing inside the library if possible or we accept it won't highlight

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
        )  # URL expires in 1 hour
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

def create_flask_app():
    app = Flask(__name__)

    database_uri = os.getenv("DATABASE_URL", "sqlite:///:memory:")#fallback to in-memory SQLite if DATABASE_URL is not set TODO: fix this as might fallback in production if env var is missing
    app.config["SQLALCHEMY_DATABASE_URI"] = database_uri

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
