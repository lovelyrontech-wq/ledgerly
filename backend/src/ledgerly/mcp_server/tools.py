"""What each MCP tool does. Plain functions: a database session and the signed-in user's ID in,
JSON-ready dicts out. server.py registers them as MCP tools.

Every function checks folder permissions for `user_id`, so the agent can never see or change
more than the signed-in user could in the app.

The approval rule: preview_bulk_update does NOT return the approval code (the preview hash).
Only the user's app gets it, from GET /api/batches/{id}, and sends it when the user clicks
Approve. So the agent cannot apply a change the user has not approved.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ledgerly.db.models import Batch, LedgerRecord
from ledgerly.knowledge.help_docs import HelpDocs
from ledgerly.permissions import FolderNotFound, PermissionDenied, Role, accessible_folders, require_folder
from ledgerly.services import batches

# Most items a tool returns, so a large folder does not flood the model's context.
MAX_ITEMS_IN_RESULT = 50


@contextmanager
def tool_errors() -> Iterator[None]:
    """Turn expected failures into ToolError, whose message the model sees and can act on."""
    try:
        yield
    except FolderNotFound:
        raise ToolError("Folder not found, or you do not have access to it.") from None
    except PermissionDenied as exc:
        raise ToolError(f"You need {exc.required.label} access to do this (you are {exc.actual.label}).") from None
    except batches.BatchNotFound:
        raise ToolError("Batch not found, or you do not have access to it.") from None
    except batches.BatchConflict as exc:
        raise ToolError(str(exc)) from None


def _money(cents: int, currency: str) -> str:
    return f"{Decimal(cents) / 100:,.2f} {currency}"


def list_folders(session: Session, user_id: str) -> dict[str, Any]:
    folders = accessible_folders(session, user_id)
    return {"folders": [{"id": f.id, "name": f.name, "type": f.type, "yourRole": role.label} for f, role in folders]}


def list_records(
    session: Session, user_id: str, folder_id: str, status: str | None = None, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    with tool_errors():
        folder, role = require_folder(session, user_id, folder_id, Role.VIEWER)
    limit = max(1, min(limit, MAX_ITEMS_IN_RESULT))
    offset = max(0, offset)

    query = select(LedgerRecord).where(LedgerRecord.folder_id == folder_id)
    if status is not None:
        query = query.where(LedgerRecord.status == status)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(LedgerRecord.name, LedgerRecord.id).limit(limit).offset(offset)).all()
    return {
        "folder": {"id": folder.id, "name": folder.name, "type": folder.type, "yourRole": role.label},
        "total": total,
        "offset": offset,
        "records": [
            {
                "id": r.id,
                "name": r.name,
                "value": _money(r.value_cents, r.currency),
                "valueCents": r.value_cents,
                "status": r.status,
                "version": r.version,
            }
            for r in rows
        ],
    }


def _batch_result(batch: Batch, message: str) -> dict[str, Any]:
    items = sorted(batch.items, key=lambda i: (i.record.name, i.record_id))
    summary: dict[str, int] = {}
    for item in items:
        summary[item.result or "pending"] = summary.get(item.result or "pending", 0) + 1
    shown = items[:MAX_ITEMS_IN_RESULT]
    currency = items[0].record.currency if items else ""
    return {
        "batchId": batch.id,
        "folderId": batch.folder_id,
        "status": batch.status,
        "instruction": batch.instruction,
        "recordCount": len(items),
        "totalBefore": _money(sum(i.before for i in items), currency),
        "totalAfter": _money(sum(i.after for i in items), currency),
        "summary": summary,
        "changes": [
            {
                "recordId": i.record_id,
                "name": i.record.name,
                "before": _money(i.before, i.record.currency),
                "after": _money(i.after, i.record.currency),
                "result": i.result,
                "error": i.error,
            }
            for i in shown
        ],
        "changesNotShown": len(items) - len(shown),
        "message": message,
    }


def preview_bulk_update(
    session: Session,
    user_id: str,
    folder_id: str,
    percent: Decimal,
    instruction: str,
    ttl_minutes: int,
    status: str | None = None,
) -> dict[str, Any]:
    with tool_errors():
        batch = batches.create_preview(session, user_id, folder_id, percent, instruction, ttl_minutes, status)
    session.commit()
    return _batch_result(
        batch,
        "Nothing has changed yet. Show this preview to the user and ask them to approve it in the app. "
        "Do not call apply_bulk_update until the user has approved; the app gives you the approval code.",
    )


def apply_bulk_update(session: Session, user_id: str, batch_id: str, approval_code: str) -> dict[str, Any]:
    # Derived from the batch and the approval, so retrying the same approval never applies twice.
    idempotency_key = f"mcp:{batch_id}:{approval_code[:32]}"
    try:
        with tool_errors():
            batch = batches.apply_batch(session, user_id, batch_id, approval_code, idempotency_key)
    except ToolError:
        session.commit()  # keeps an "expired" status; nothing else was written
        raise
    session.commit()
    skipped = sum(1 for i in batch.items if i.result == "skipped_changed")
    message = "Applied. The user can undo this batch."
    if skipped:
        message += f" {skipped} record(s) changed after the preview and were skipped, not overwritten."
    return _batch_result(batch, message)


def undo_batch(session: Session, user_id: str, batch_id: str) -> dict[str, Any]:
    with tool_errors():
        batch = batches.undo_batch(session, user_id, batch_id)
    session.commit()
    kept = sum(1 for i in batch.items if i.result == "undo_skipped")
    message = "Undone. Old values are restored."
    if kept:
        message += f" {kept} record(s) were edited after the update and were left as they are."
    return _batch_result(batch, message)


def search_help_docs(docs_dir: Path, query: str, limit: int = 3) -> dict[str, Any]:
    results = HelpDocs.load(docs_dir).search(query, limit=max(1, min(limit, 5)))
    return {
        "query": query,
        "results": [{"title": r.title, "source": r.source, "text": r.text, "score": r.score} for r in results],
    }
