from flask import Flask, request, jsonify
from flask import Blueprint
from space_generator import llm_fact



test = Blueprint('test', __name__, url_prefix='/test')
healthcheck = Blueprint('healthcheck', __name__, url_prefix='/healthcheck')


@test.route("/")
def hello_world():
    return "<p>Hello, World!</p>"


@test.route('/funfact')
def space_greetings():
    response = llm_fact()

    return jsonify({
        "funfact": response
    })

@healthcheck.route("/ready")
def ready():
    return "<p>Roger, Roger! Application OK."

def create_app():
    app = Flask(__name__)
    app.register_blueprint(test)
    app.register_blueprint(healthcheck)

    return app

if __name__ == '__main__':  
    create_app().run(host='0.0.0.0', port=3000) 