from flask import Flask, request, jsonify
from flask import Blueprint
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
import os
from scripts.pipeline.worker import run_counter, llm_fact, list_s3_directories, counter_call_back
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=4)

from src.web_browser import routing

root = Blueprint('test', __name__, url_prefix='/')
healthcheck = Blueprint('healthcheck', __name__, url_prefix='/healthcheck')
viewer = Blueprint('viewer', __name__, url_prefix='/viewer')
worker = Blueprint('worker', __name__, url_prefix='/worker')

db = SQLAlchemy()
global_config = {}

class Test(db.Model):
    info: Mapped[str] = mapped_column(primary_key=True)


@root.route("/")
def db_test():
    test = db.first_or_404(db.select(Test))
    return "<p>Hello, World! " + test.info + "</p>" 


@worker.route("/test")
def counter():
    raw_val = request.args.get('no')

    if raw_val is not None and raw_val.isdigit():
        number = int(raw_val)
        future_task = executor.submit(run_counter, number)
        result = counter_call_back(future_task)


        return jsonify({"status": result})





@worker.route("/list")
def s3_check():
    bucket = request.args.get('bucket')
    prefix = request.args.get('prefix', '')

    if not bucket:
        return jsonify({"error": "Bucket name is required"}), 400

    try:
        response  = list_s3_directories(bucket, prefix)
        directories = [
            item['Prefix'] for item in response.get('CommonPrefixes', [])
        ]

        return jsonify({
            "status": "success",
            "bucket": bucket,
            "directories": directories
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



@worker.route("/llm")
def space_greetings():
    response = llm_fact()

    return jsonify({
        "funfact": response
    })



@healthcheck.route("/ready")
def ready():
    return "<p>Roger, Roger! Application is ready."

@viewer.route("/bucket")
def viewer_load():
    return routing.index(global_config)

def create_app():
    app = Flask(__name__)
    app.register_blueprint(root)
    app.register_blueprint(healthcheck)
    app.register_blueprint(viewer)
    app.register_blueprint(worker)

    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    db.init_app(app)

    return app

if __name__ == '__main__':  
    create_app().run(host='0.0.0.0', port=3000) 