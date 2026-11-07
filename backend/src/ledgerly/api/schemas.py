"""Request and response bodies. JSON uses camelCase for the Next.js frontend."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


def _as_utc(value: datetime) -> datetime:
    # SQLite returns datetimes without a timezone. All stored times are UTC, so say so;
    # otherwise browsers read "2026-07-01T09:00:00" as local time.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


UtcDateTime = Annotated[datetime, AfterValidator(_as_utc)]


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True, extra="forbid")


# -------------Auth---------------
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
    status: str | None = None
    fields: dict[str, Any] | None = None


class ErrorOut(ApiModel):
    detail: str


class PreviewRequest(ApiModel):
    """Change every matching record's value by `percent` (10 = +10%, -5 = -5%)."""

    percent: Decimal = Field(ge=-100, le=1000, max_digits=7, decimal_places=2)
    instruction: str = Field(min_length=1, max_length=500)
    status: str | None = Field(default=None, max_length=20)


class ApplyRequest(ApiModel):
    # The previewHash from the preview the user approved.
    preview_hash: str = Field(min_length=64, max_length=64)


class BatchItemOut(ApiModel):
    record_id: str
    record_name: str
    field: str
    before: int
    after: int
    expected_version: int
    result: str | None
    error: str | None


class BatchOut(ApiModel):
    id: str
    folder_id: str
    created_by: str
    status: str
    instruction: str
    preview_hash: str
    created_at: UtcDateTime
    expires_at: UtcDateTime | None
    applied_at: UtcDateTime | None
    undone_at: UtcDateTime | None
    # Count of items per result, e.g. {"applied": 39, "skipped_changed": 1}
    summary: dict[str, int]
    items: list[BatchItemOut]

# -------------Agent---------------
class AgentChatRequest(ApiModel):
    message: str = Field(min_length=1, max_length=4000)
    # Leave out to start a new conversation.
    conversation_id: str | None = Field(default=None, max_length=64)
    # The folder the user is looking at, so "this folder" means something.
    folder_id: str | None = Field(default=None, max_length=64)


class AgentBatchRequest(ApiModel):
    conversation_id: str = Field(min_length=1, max_length=64)
    batch_id: str = Field(min_length=1, max_length=64)
