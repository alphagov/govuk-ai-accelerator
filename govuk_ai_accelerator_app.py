from flask import Flask, request
from flask import Blueprint
from space_generator import funfact


test = Blueprint('test', __name__, url_prefix='/test')
healthcheck = Blueprint('healthcheck', __name__, url_prefix='/healthcheck')
funfact = Blueprint('funfact', __name__, url_prefix='/funfact')



@test.route("/")
def hello_world():
    return "<p>Hello, World!</p>"


@funfact.route('/funfact')
def funfact():
    query = request.args.get('greetings') 
    response = funfact(query)
    return jsonify({
        "funfact": response
    })


@healthcheck.route("/ready")
def ready():
    return "<p>Application OK"

def create_app():
    app = Flask(__name__)
    app.register_blueprint(test)
    app.register_blueprint(healthcheck)
    app.register_blueprint(funfact)

    return app

if __name__ == '__main__':  
    create_app().run(host='0.0.0.0', port=3000) 