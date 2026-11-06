"""Read and edit a single record."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import update

from ledgerly.api.deps import CurrentUser, SessionDep
from ledgerly.api.schemas import RecordOut, RecordUpdate
from ledgerly.db.models import AuditLog, Folder, LedgerRecord, utcnow
from ledgerly.permissions import FolderNotFound, Role, require_folder

router = APIRouter(prefix="/api/records", tags=["records"])

STATUSES_BY_FOLDER_TYPE = {
    "invoice": {"draft", "sent", "paid", "overdue"},
    "product": {"active", "archived"},
}


def _load_record(session: SessionDep, user_id: str, record_id: str, minimum: Role) -> tuple[LedgerRecord, Folder]:
    record = session.get(LedgerRecord, record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    try:
        folder, _ = require_folder(session, user_id, record.folder_id, minimum)
    except FolderNotFound:
        # Same answer as a missing record: don't reveal records in folders you can't see.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found") from None
    return record, folder


@router.get("/{record_id}", response_model=RecordOut)
def get_record(record_id: str, user: CurrentUser, session: SessionDep) -> RecordOut:
    record, _ = _load_record(session, user.id, record_id, Role.VIEWER)
    return RecordOut.model_validate(record)


@router.patch(
    "/{record_id}",
    response_model=RecordOut,
    responses={409: {"description": "The record changed since you loaded it"}},
)
def update_record(record_id: str, body: RecordUpdate, user: CurrentUser, session: SessionDep) -> RecordOut:
    record, folder = _load_record(session, user.id, record_id, Role.EDITOR)

    if body.status is not None and body.status not in STATUSES_BY_FOLDER_TYPE[folder.type]:
        allowed = ", ".join(sorted(STATUSES_BY_FOLDER_TYPE[folder.type]))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid status for a {folder.type}. Allowed: {allowed}",
        )

    changes: dict[str, Any] = body.model_dump(exclude_unset=True, exclude={"version"})
    if not changes:
        return RecordOut.model_validate(record)

    before = {field: getattr(record, field) for field in changes}

    # Compare-and-set in one UPDATE: only writes if the version is still the one the client saw.
    # This stays correct even if two requests race, unlike a read-then-check in Python.
    result = session.execute(
        update(LedgerRecord)
        .where(LedgerRecord.id == record_id, LedgerRecord.version == body.version)
        .values(**changes, version=LedgerRecord.version + 1, updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This record was changed by someone else. Reload it and try again.",
        )

    session.add(
        AuditLog(
            user_id=user.id,
            action="record.update",
            details={"recordId": record_id, "before": before, "after": changes, "version": body.version + 1},
        )
    )
    session.commit()
    session.refresh(record)
    return RecordOut.model_validate(record)
