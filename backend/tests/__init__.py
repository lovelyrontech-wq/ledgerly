"""Per-user folder access.

Roles, from most to least access: owner > editor > viewer.
- owner: the folder's owner_id. Full access.
- editor: can read and change records, and approve bulk updates.
- viewer: read only.

A user with no role on a folder gets 404, not 403, so they cannot tell whether it exists.
A user with too low a role gets 403.
"""

from __future__ import annotations

from enum import IntEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerly.db.models import Folder, FolderPermission

class Role(IntEnum):
    VIEWER = 1
    EDITOR = 2
    OWNER = 3

    @property
    def label(self) -> str:
        return self.name.lower()

class FolderNotFound(Exception):
    """The folder does not exist, or the user has no access to it."""

class PermissionDenied(Exception):
    def __init__(self,required:Role,actual:Role) -> None:
        super().__init__(f"requires {required.label}, you are {actual.label}")
        self.required = required
        self.actual = actual

def folder_role(session:Session, user_id:str, folder: Folder) -> Role | None:
    if folder.owner_id == user_id:
        return Role.OWNER
    share = session.get(FolderPermission, (folder.id,user_id))
    if share is None:
        return None
    return Role.EDITOR if share.role == "editor" else Role.VIEWER

def require_folder(session: Session, user_id:str, folder_id: str, minimum: Role) -> tuple[Folder, Role]:
    """Load a folder the user may access with at least minimum role."""
    folder = session.get(Folder, folder_id)
    role = folder_role(session, user_id, folder) if folder else None

    if folder is None or role is None:
        raise FolderNotFound
    if role < minimum:
        raise PermissionDenied(minimum, role)
    return folder, role

def accessible_folders(session:Session, user_id: str) -> list[tuple[Folder, Role]]:
    """Every Folder the user own or has been shared ,with their role, sorted by name."""

    owned = session.scalars(select(Folder).where(Folder.owner_id == user_id)).all()
    shared = session.execute(
        select(Folder, FolderPermission.role)
        .join(FolderPermission, FolderPermission.folder_id == Folder.id)
        .where(FolderPermission.user_id == user_id)
    ).all()
    result = [(f, Role.OWNER) for f in owned]
    result += [(f, Role.EDITOR if r == "editor" else Role.VIEWER) for f,r in shared]
    return sorted(result, key= lambda pair: pair[0].name.lower())
