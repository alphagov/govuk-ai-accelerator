from flask import Flask
from flask import Blueprint


test = Blueprint('admin', __name__, url_prefix='/test')

@test.route("/")
def hello_world():
    return "<p>Hello, World!</p>"


def create_app():
    app = Flask(__name__)
    app.register_blueprint(test)

    return app

if __name__ == '__main__':  
    create_app().run(host='0.0.0.0', port=8080) 