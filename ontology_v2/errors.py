from flask import jsonify
from pydantic import ValidationError

from ontology_v2.schemas import UnknownTaskError


def error_response(code: str, message: str, status: int):
    response = jsonify({"error": code, "message": message})
    response.status_code = status
    return response


def map_pydantic_error(exc: ValidationError) -> tuple[str, str]:
    for err in exc.errors():
        original = err.get("ctx", {}).get("error")
        if isinstance(original, UnknownTaskError):
            return "unknown_task", f"unknown tasks: {original.unknown}"
    first = exc.errors()[0]
    loc = ".".join(str(p) for p in first["loc"])
    return "validation_error", f"{loc}: {first['msg']}"