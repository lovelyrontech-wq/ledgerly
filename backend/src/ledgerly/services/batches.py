"""Bulk updates: preview -> approve -> apply -> undo.

Guardrails:
- A preview stores the exact record IDs, old value, new value, and the record version it saw.
- Apply needs the preview hash, so the user approves exactly what they saw, nothing else.
- Apply needs an Idempotency-Key. Sending the same key again returns the stored result
  instead of applying twice.
- Each record is written only if its version still matches the preview. Records changed
  since then are skipped (result "skipped_changed"), never overwritten.
- Undo restores a record only if nobody changed it after the apply ("undo_skipped" otherwise).
- Every step is written to the audit log.

These functions do not commit. The caller owns the transaction, so a failure rolls back
everything, including the audit entry.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from ledgerly.db.models import AuditLog, Batch, BatchItem, LedgerRecord, utcnow
from ledgerly.permissions import FolderNotFound, Role, require_folder

MAX_BATCH_RECORDS = 1000


class BatchNotFound(Exception):
    """The batch does not exist, or the user cannot see its folder."""


class BatchConflict(Exception):
    """The batch is in the wrong state for this action, or the request does not match it."""


class BatchExpired(BatchConflict):
    """The preview is too old to approve. The caller should commit, so the batch is marked expired."""


def _as_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes; everything is stored in UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def apply_percent(value_cents: int, percent: Decimal) -> int:
    """value * (1 + percent/100), rounded half-up to whole cents, never below 0."""
    new = (Decimal(value_cents) * (Decimal(100) + percent) / Decimal(100)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return max(int(new), 0)


def preview_hash(batch_id: str, items: Sequence[BatchItem]) -> str:
    """Fingerprint of exactly what the user is approving: batch, record IDs, old and new values, versions."""
    parts = [batch_id] + [
        f"{i.record_id}:{i.before}:{i.after}:{i.expected_version}" for i in sorted(items, key=lambda i: i.record_id)
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def load_batch(session: Session, user_id: str, batch_id: str, minimum: Role) -> Batch:
    batch = session.scalar(
        select(Batch).where(Batch.id == batch_id).options(selectinload(Batch.items).selectinload(BatchItem.record))
    )
    if batch is None:
        raise BatchNotFound(batch_id)
    try:
        require_folder(session, user_id, batch.folder_id, minimum)
    except FolderNotFound:
        # Same answer as a missing batch: don't reveal batches in folders you can't see.
        raise BatchNotFound(batch_id) from None
    return batch


def create_preview(
    session: Session,
    user_id: str,
    folder_id: str,
    percent: Decimal,
    instruction: str,
    ttl_minutes: int,
    status: str | None = None,
) -> Batch:
    """Compute old -> new for every matching record and store it as a pending batch. Writes no records."""
    require_folder(session, user_id, folder_id, Role.EDITOR)

    query = select(LedgerRecord).where(LedgerRecord.folder_id == folder_id)
    if status is not None:
        query = query.where(LedgerRecord.status == status)
    records = session.scalars(query.order_by(LedgerRecord.name, LedgerRecord.id)).all()
    if not records:
        raise BatchConflict("No records match, so there is nothing to update.")
    if len(records) > MAX_BATCH_RECORDS:
        raise BatchConflict(f"Too many records ({len(records)}). The limit is {MAX_BATCH_RECORDS} per batch.")

    now = utcnow()
    batch = Batch(
        folder_id=folder_id,
        created_by=user_id,
        status="pending",
        instruction=instruction,
        created_at=now,
        expires_at=now + timedelta(minutes=ttl_minutes),
    )
    batch.items = [
        BatchItem(
            record_id=r.id,
            record=r,
            field="value_cents",
            before=r.value_cents,
            after=apply_percent(r.value_cents, percent),
            expected_version=r.version,
        )
        for r in records
    ]
    session.add(batch)
    session.flush()  # assigns batch.id

    session.add(
        AuditLog(
            user_id=user_id,
            action="batch.preview",
            batch_id=batch.id,
            details={"folderId": folder_id, "percent": str(percent), "status": status, "records": len(records)},
        )
    )
    return batch


def apply_batch(session: Session, user_id: str, batch_id: str, approved_hash: str, idempotency_key: str) -> Batch:
    """Apply an approved preview. Safe to retry with the same idempotency key."""
    # Retry of an earlier apply: return the stored result, write nothing.
    previous = session.scalar(select(Batch).where(Batch.idempotency_key == idempotency_key))
    if previous is not None:
        if previous.id != batch_id:
            raise BatchConflict("This Idempotency-Key was already used for a different batch.")
        return load_batch(session, user_id, batch_id, Role.VIEWER)

    batch = load_batch(session, user_id, batch_id, Role.EDITOR)
    if batch.status != "pending":
        raise BatchConflict(f"This batch is {batch.status}, so it cannot be applied.")
    if batch.expires_at is not None and _as_utc(batch.expires_at) <= utcnow():
        batch.status = "expired"
        session.flush()
        raise BatchExpired("This preview has expired. Create a new preview.")
    if approved_hash != preview_hash(batch.id, batch.items):
        raise BatchConflict("The approval does not match this preview. Reload the preview and approve again.")

    now = utcnow()
    # Claim the batch in one statement. If two applies race, only one gets rowcount 1.
    claimed = session.execute(
        update(Batch)
        .where(Batch.id == batch.id, Batch.status == "pending")
        .values(status="applied", applied_at=now, idempotency_key=idempotency_key)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:  # type: ignore[attr-defined]
        raise BatchConflict("This batch was applied by another request.")

    for item in batch.items:
        result = session.execute(
            update(LedgerRecord)
            .where(LedgerRecord.id == item.record_id, LedgerRecord.version == item.expected_version)
            .values(value_cents=item.after, version=LedgerRecord.version + 1, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:  # type: ignore[attr-defined]
            item.result = "applied"
        else:
            item.result = "skipped_changed"
            item.error = "The record changed after the preview, so it was not updated."

    session.add(
        AuditLog(
            user_id=user_id,
            action="batch.apply",
            batch_id=batch.id,
            details={"idempotencyKey": idempotency_key, **_counts(batch.items)},
        )
    )
    session.flush()
    session.expire_all()  # reload status, versions and values written by the UPDATEs above
    return load_batch(session, user_id, batch_id, Role.VIEWER)


def undo_batch(session: Session, user_id: str, batch_id: str) -> Batch:
    """Put back the old values of an applied batch, for records nobody changed since."""
    batch = load_batch(session, user_id, batch_id, Role.EDITOR)
    if batch.status != "applied":
        raise BatchConflict(f"This batch is {batch.status}, so it cannot be undone.")

    now = utcnow()
    claimed = session.execute(
        update(Batch)
        .where(Batch.id == batch.id, Batch.status == "applied")
        .values(status="undone", undone_at=now)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:  # type: ignore[attr-defined]
        raise BatchConflict("This batch was undone by another request.")

    for item in batch.items:
        if item.result != "applied":
            continue
        # The apply moved the record to expected_version + 1. Any other version means someone edited it since.
        result = session.execute(
            update(LedgerRecord)
            .where(LedgerRecord.id == item.record_id, LedgerRecord.version == item.expected_version + 1)
            .values(value_cents=item.before, version=LedgerRecord.version + 1, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:  # type: ignore[attr-defined]
            item.result = "undone"
        else:
            item.result = "undo_skipped"
            item.error = "The record changed after the update, so it was not restored."

    session.add(AuditLog(user_id=user_id, action="batch.undo", batch_id=batch.id, details=_counts(batch.items)))
    session.flush()
    session.expire_all()
    return load_batch(session, user_id, batch_id, Role.VIEWER)


def _counts(items: Sequence[BatchItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = item.result or "pending"
        counts[key] = counts.get(key, 0) + 1
    return counts
