"""Bulk updates: preview, apply (with approval and Idempotency-Key), undo."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header

from ledgerly.api.deps import CurrentUser, SessionDep, SettingsDep
from ledgerly.api.schemas import ApplyRequest, BatchItemOut, BatchOut, PreviewRequest
from ledgerly.db.models import Batch
from ledgerly.permissions import Role
from ledgerly.services import batches as service

router = APIRouter(tags=["batches"])

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]


def batch_out(batch: Batch) -> BatchOut:
    items = sorted(batch.items, key=lambda i: (i.record.name, i.record_id))
    summary: dict[str, int] = {}
    for item in items:
        key = item.result or "pending"
        summary[key] = summary.get(key, 0) + 1
    return BatchOut(
        id=batch.id,
        folder_id=batch.folder_id,
        created_by=batch.created_by,
        status=batch.status,
        instruction=batch.instruction,
        preview_hash=service.preview_hash(batch.id, items),
        created_at=batch.created_at,
        expires_at=batch.expires_at,
        applied_at=batch.applied_at,
        undone_at=batch.undone_at,
        summary=summary,
        items=[
            BatchItemOut(
                record_id=i.record_id,
                record_name=i.record.name,
                field=i.field,
                before=i.before,
                after=i.after,
                expected_version=i.expected_version,
                result=i.result,
                error=i.error,
            )
            for i in items
        ],
    )


@router.post("/api/folders/{folder_id}/batches/preview", response_model=BatchOut, status_code=201)
def preview(
    folder_id: str, body: PreviewRequest, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> BatchOut:
    """Show old -> new for every record. Nothing is changed until the batch is applied."""
    batch = service.create_preview(
        session,
        user.id,
        folder_id,
        percent=body.percent,
        instruction=body.instruction,
        ttl_minutes=settings.batch_preview_ttl_minutes,
        status=body.status,
    )
    session.commit()
    return batch_out(batch)


@router.get("/api/batches/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: str, user: CurrentUser, session: SessionDep) -> BatchOut:
    return batch_out(service.load_batch(session, user.id, batch_id, Role.VIEWER))


@router.post("/api/batches/{batch_id}/apply", response_model=BatchOut)
def apply(
    batch_id: str, body: ApplyRequest, idempotency_key: IdempotencyKey, user: CurrentUser, session: SessionDep
) -> BatchOut:
    """Write the approved preview. Retrying with the same Idempotency-Key returns the same result."""
    try:
        batch = service.apply_batch(session, user.id, batch_id, body.preview_hash, idempotency_key)
    except service.BatchExpired:
        session.commit()  # keep the "expired" status
        raise
    session.commit()
    return batch_out(batch)


@router.post("/api/batches/{batch_id}/undo", response_model=BatchOut)
def undo(batch_id: str, user: CurrentUser, session: SessionDep) -> BatchOut:
    """Restore the old values. Records changed since the apply are left alone and reported."""
    batch = service.undo_batch(session, user.id, batch_id)
    session.commit()
    return batch_out(batch)