import json
from uuid import UUID, uuid4

from flask import Blueprint, jsonify, request, url_for
from pydantic import ValidationError

from govuk_ai_accelerator_app import db
from ontology_v2.errors import error_response, map_pydantic_error
from ontology_v2.models import V2OntologyRun
from ontology_v2.schemas import CreateRunRequest, RunResponse
from ontology_v2.openapi import build_openapi_spec

ontology_v2_bp = Blueprint("ontology_v2", __name__, url_prefix="/ontology-v2")

SCALAR_HTML = """<!doctype html>
<html><head><title>Ontology v2 API</title><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" /></head>
<body>
<script id="api-reference" data-url="/ontology-v2/openapi.json"></script>
<script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
</body></html>
"""

def _serialize(run: V2OntologyRun) -> dict:
    return RunResponse.model_validate(run, from_attributes=True).model_dump(mode="json")


@ontology_v2_bp.route("/runs", methods=["POST"])
def create_run():
    if request.mimetype != "application/json":
        return error_response("unsupported_media_type", "Content-Type must be application/json", 415)

    try:
        payload = json.loads(request.get_data(as_text=True))
    except json.JSONDecodeError:
        return error_response("malformed_request", "Body is not valid JSON", 400)

    try:
        parsed = CreateRunRequest.model_validate(payload)
    except ValidationError as exc:
        code, message = map_pydantic_error(exc)
        return error_response(code, message, 400)

    run = V2OntologyRun(
        run_id=uuid4(),
        status="pending",
        domain=parsed.domain,
        tasks=parsed.tasks,
    )
    db.session.add(run)
    db.session.commit()

    location = url_for("ontology_v2.get_run", run_id=str(run.run_id))
    return _serialize(run), 201, {"Location": location}


@ontology_v2_bp.route("/runs/<run_id>", methods=["GET"])
def get_run(run_id: str):
    try:
        parsed_id = UUID(run_id)
    except ValueError:
        return error_response("invalid_run_id", f"{run_id!r} is not a valid UUID", 400)

    run = db.session.get(V2OntologyRun, parsed_id)
    if run is None:
        return error_response("run_not_found", f"No run with id {parsed_id}", 404)

    return _serialize(run), 200

@ontology_v2_bp.route("/openapi.json", methods=["GET"])
def openapi_spec():
    return jsonify(build_openapi_spec()), 200

@ontology_v2_bp.route("/docs", methods=["GET"])
def scalar_docs():
    return SCALAR_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}