"""GOV.UK AI Accelerator Flask Application."""

import os
import yaml
from uuid import uuid4
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, Blueprint
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.exc import OperationalError

from scripts.pipeline.ontology_generator import run_ontology_background_task
from scripts.pipeline.utils import error_response, is_yaml_file, executor
from scripts.pipeline.constants import APP_HOST, APP_PORT, BLUEPRINTS

# Initialize database extension without app binding
db = SQLAlchemy()


class ProcessingJob(db.Model):
    """Model to track the status of submitted jobs."""

    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String)
    domain: Mapped[str] = mapped_column(String, nullable=True)
    error_message: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))


def create_blueprints():
    """Create and register blueprints."""
    healthcheck_bp = Blueprint('healthcheck', __name__, url_prefix=BLUEPRINTS['healthcheck']['prefix'])
    ontology_bp = Blueprint('ontology', __name__, url_prefix=BLUEPRINTS['ontology']['prefix'])

    @healthcheck_bp.route("/ready")
    def health_check():
        return {"status": "healthy", "message": "Application is ready"}, 200

    @ontology_bp.route("/", methods=['GET'])
    def index():
        return render_template('upload.html')

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

            # try to create a tracking record; if the database is unreachable we
            # log a warning and proceed without persistence.  In that case we do
            # not pass the job_id to the background task so it won't attempt
            # further updates.
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
        return jsonify({"job_id": job.id, "status": job.status})

    return healthcheck_bp, ontology_bp


def create_app():
    app = Flask(__name__)
    database_uri = os.getenv("DATABASE_URL", "sqlite:///:memory:")#fallback to in-memory SQLite if DATABASE_URL is not set TODO: fix this as might fallback in production if env var is missing
    app.config["SQLALCHEMY_DATABASE_URI"] = database_uri

    db.init_app(app)

    healthcheck_bp, ontology_bp = create_blueprints()
    app.register_blueprint(healthcheck_bp)
    app.register_blueprint(ontology_bp)

    with app.app_context():
        try:
            db.create_all()
        except Exception as exc: 
            from sqlalchemy.exc import OperationalError
            if isinstance(exc, OperationalError):
                app.logger.warning("Could not initialize database: %s. Proceeding without database.",exc,)
            else:
                raise

    return app


if __name__ == '__main__':
    app_instance = create_app()
    app_instance.run(host=APP_HOST, port=APP_PORT, debug=False)
