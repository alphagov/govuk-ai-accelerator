from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

ALLOWED_TASKS: frozenset[str] = frozenset()

class UnknownTaskError(ValueError):
    def __init__(self, unknown: list[str]) -> None:
        self.unknown = unknown
        super().__init__(f"unknown tasks: {unknown}")


class CreateRunRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9-]+$")
    tasks: list[str] = Field(min_length=1)

    @field_validator("tasks")
    @classmethod
    def _no_blank_strings(cls, value):
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("tasks entries must be non-blank strings")
        return value

    @field_validator("tasks")
    @classmethod
    def _all_known(cls, value):
        unknown = [t for t in value if t not in ALLOWED_TASKS]
        if unknown:
            raise UnknownTaskError(unknown)
        return value


class RunResponse(BaseModel):
    run_id: UUID
    status: str
    domain: str
    tasks: list[str]
    created_at: datetime


class ErrorResponse(BaseModel):
    error: str
    message: str