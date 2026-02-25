import boto3
from flask import Flask, render_template


def index(app) -> str:
    app = Flask(__name__)
    if "AWS_KWARGS" in app.config:
        s3 = boto3.resource("s3", app.config["AWS_KWARGS"])
        all_buckets = s3.buckets.all()
        return render_template("index.html", buckets=all_buckets)
    else:
        return render_template("error.html", error="The specified bucket does not exist.")