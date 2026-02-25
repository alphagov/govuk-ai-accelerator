from flask import Flask, request, jsonify, render_template
from flask import Blueprint
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
import yaml
import os
from scripts.pipeline.worker import run_counter, llm_fact, list_s3_directories, future_call_back
from scripts.pipeline.ontology_generator import run_ontology_background_task
from scripts.pipeline.utils import _error_response, _is_yaml_file, executor





root = Blueprint('test', __name__, url_prefix='/') #TODO: Remove when test is done
healthcheck = Blueprint('healthcheck', __name__, url_prefix='/healthcheck')
worker = Blueprint('worker', __name__, url_prefix='/worker') #TODO: Remove when test is done
ontology_bp = Blueprint('ontology', __name__, url_prefix='/ontology')


db = SQLAlchemy()

class Test(db.Model):
    info: Mapped[str] = mapped_column(primary_key=True)


@root.route("/")
def db_test():
    test = db.first_or_404(db.select(Test))
    return "<p>Hello, World! " + test.info + "</p>" 




@ontology_bp.route("/")
def index():
    return render_template('upload.html')


@ontology_bp.route('/submit', methods=['POST'])
def upload_file():
    ''' handling file upload from the form '''
    if 'file' not in request.files:
        return _error_response("Configuration file is missing")
        
    yaml_file = request.files['file']

    if yaml_file.filename == '' or not _is_yaml_file(yaml_file.filename):
        return _error_response("Invalid YAML file.")

    try:
        config_data = yaml.safe_load(yaml_file)
        
        executor.submit(run_ontology_background_task, config_data)
        
            
        return jsonify({
            "message": "Background pipeline started",
            "status": 'pending'
        })

    except Exception as e:
        return _error_response(f"Upload failed: {str(e)}", 500)






@healthcheck.route("/ready")
def ready():
    return "<p>Roger, Roger! Application is ready."

def create_app():
    app = Flask(__name__)
    app.register_blueprint(root)
    app.register_blueprint(healthcheck)
    app.register_blueprint(worker)
    app.register_blueprint(ontology_bp)

    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    db.init_app(app)

    return app

if __name__ == '__main__':  
    create_app().run(host='0.0.0.0', port=3000) 