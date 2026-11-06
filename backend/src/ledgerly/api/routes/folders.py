"""Folders the signed-in user can access, and the records in them."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from ledgerly.api.deps import CurrentUser, SessionDep
from ledgerly.api.schemas import FolderOut, RecordOut, RecordPage
from ledgerly.db.models import Folder, LedgerRecord
from ledgerly.permissions import Role, accessible_folders, require_folder

router = APIRouter(prefix="/api/folders", tags=["folders"])


def _folder_out(folder: Folder, role: Role) -> FolderOut:
    return FolderOut(
        id=folder.id,
        name=folder.name,
        type=folder.type,
        owner_id=folder.owner_id,
        role=role.label,
        created_at=folder.created_at,
    )


@router.get("", response_model=list[FolderOut])
def list_folders(user: CurrentUser, session: SessionDep) -> list[FolderOut]:
    return [_folder_out(f, role) for f, role in accessible_folders(session, user.id)]


@router.get("/{folder_id}", response_model=FolderOut)
def get_folder(folder_id: str, user: CurrentUser, session: SessionDep) -> FolderOut:
    folder, role = require_folder(session, user.id, folder_id, Role.VIEWER)
    return _folder_out(folder, role)


@router.get("/{folder_id}/records", response_model=RecordPage)
def list_records(
    folder_id: str,
    user: CurrentUser,
    session: SessionDep,
    status: Annotated[str | None, Query(max_length=20)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RecordPage:
    require_folder(session, user.id, folder_id, Role.VIEWER)

    query = select(LedgerRecord).where(LedgerRecord.folder_id == folder_id)
    if status is not None:
        query = query.where(LedgerRecord.status == status)

    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    # Sort by name, then id, so paging is stable even when names repeat.
    rows = session.scalars(query.order_by(LedgerRecord.name, LedgerRecord.id).limit(limit).offset(offset)).all()
    return RecordPage(
        items=[RecordOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
