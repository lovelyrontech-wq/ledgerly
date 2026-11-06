"""Request and response bodies. JSON uses camelCase for the Next.js frontend."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

def _as_utc(value: datetime) -> datetime:
     # SQLite returns datetimes without a timezone. All stored times are UTC, so say so;
    # otherwise browsers read "2026-07-01T09:00:00" as local time.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

UtcDateTime = Annotated[datetime, AfterValidator(_as_utc)]

class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator = to_camel, populate_by_name=True, from_attributes=True, extra = "forbid")

#-------------Auth---------------
class LoginRequest(ApiModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=4, max_length=200)

class UserOut(ApiModel):
    id: str
    email: str
    name: str

class LoginResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut

class FolderOut(ApiModel):
    id: str
    name: str
    type: str
    owner_id: str
    role: str
    created_at: UtcDateTime

class RecordOut(ApiModel):
    id: str
    folder_id: str
    name: str
    value_cents: int
    currency: str
    status: str
    fields: dict[str, Any]
    version: int
    updated_at: UtcDateTime

class RecordPage(ApiModel):
    items: list[RecordOut]
    total: int
    limit: int
    offset: int

class RecordUpdate(ApiModel):
     """Change one record. `version` must match the current version, or the update is rejected
    with 409, so two people editing at once cannot silently overwrite each other."""

     version: int = Field(ge=1)
     name: str | None = Field(default=None, min_length=1, max_length=200)
     value_cents: int | None = Field(default=None, ge=0)
     status: str | None= None
     fields: dict[str, Any] | None = None

class ErrorOut(ApiModel):
    detail: str

