from ontology_v2.schemas import CreateRunRequest, ErrorResponse, RunResponse


def build_openapi_spec() -> dict:
    error_ref = {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
    return {
        "openapi": "3.1.0",
        "info": {"title": "Ontology v2 API", "version": "0.1.0"},
        "paths": {
            "/ontology-v2/runs": {
                "post": {
                    "summary": "Create a v2 run",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {
                            "schema": {"$ref": "#/components/schemas/CreateRunRequest"}}},
                    },
                    "responses": {
                        "201": {"description": "Run created",
                                "content": {"application/json": {
                                    "schema": {"$ref": "#/components/schemas/RunResponse"}}}},
                        "400": {"description": "validation_error / malformed_request / unknown_task",
                                "content": error_ref},
                        "415": {"description": "unsupported_media_type",
                                "content": error_ref},
                    },
                },
            },
            "/ontology-v2/runs/{run_id}": {
                "get": {
                    "summary": "Read a v2 run",
                    "parameters": [{
                        "name": "run_id", "in": "path", "required": True,
                        "schema": {"type": "string", "format": "uuid"},
                    }],
                    "responses": {
                        "200": {"description": "Run details",
                                "content": {"application/json": {
                                    "schema": {"$ref": "#/components/schemas/RunResponse"}}}},
                        "400": {"description": "invalid_run_id", "content": error_ref},
                        "404": {"description": "run_not_found", "content": error_ref},
                    },
                },
            },
        },
        "components": {"schemas": {
            "CreateRunRequest": CreateRunRequest.model_json_schema(),
            "RunResponse": RunResponse.model_json_schema(),
            "ErrorResponse": ErrorResponse.model_json_schema(),
        }},
    }