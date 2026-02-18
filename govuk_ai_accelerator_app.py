from flask import Flask
from flask import Blueprint
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
import os

root = Blueprint('test', __name__, url_prefix='/')
healthcheck = Blueprint('healthcheck', __name__, url_prefix='/healthcheck')

db = SQLAlchemy()

class Test(db.Model):
    info: Mapped[str] = mapped_column(primary_key=True)


@root.route("/")
def db_test():
    test = db.first_or_404(db.select(Test))
    return "<p>Hello, World! " + test.info + "</p>" 

@healthcheck.route("/ready")
def ready():
    return "<p>Roger, Roger! Application is ready."

def create_app():
    app = Flask(__name__)
    app.register_blueprint(root)
    app.register_blueprint(healthcheck)

    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    db.init_app(app)

    return app

if __name__ == '__main__':  
    create_app().run(host='0.0.0.0', port=3000) 