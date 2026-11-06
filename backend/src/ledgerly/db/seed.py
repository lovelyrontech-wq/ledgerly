"""Load data/seed/*.json into the database.

Safe to re-run: clears the tables, then inserts everything in one transaction.
Run (from backend/):  uv run python -m ledgerly.db.seed
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import bcrypt
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ledgerly.config import get_settings
from ledgerly.db.models import (
    AuditLog,
    Batch,
    BatchItem,
    Folder,
    FolderPermission,
    LedgerRecord,
    User,
)
from ledgerly.db.session import get_engine, session_factory

MIN_PASSWORD_LENGTH = 8

# Children before parents, so foreign keys are never violated while clearing.
TABLES_IN_DELETE_ORDER = (AuditLog, BatchItem, Batch, LedgerRecord, FolderPermission, Folder, User)


class SeedError(Exception):
    pass


def _load(seed_dir: Path, name: str) -> list[dict[str, Any]]:
    path = seed_dir / f"{name}.json"
    if not path.exists():
        raise SeedError(f"Missing seed file: {path}. Run: python scripts/generate_sample_data.py")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SeedError(f"{path} must contain a JSON list")
    return data


def _dt(value: str | None) -> datetime | None:
    # The JSON uses JS-style ISO strings ending in "Z"; fromisoformat accepts that.
    return datetime.fromisoformat(value) if value else None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def seed(session: Session, seed_dir: Path, demo_password: str) -> dict[str, int]:
    """Replace all data with the seed data. The caller owns the transaction."""
    if len(demo_password) < MIN_PASSWORD_LENGTH:
        raise SeedError(f"SEED_DEMO_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters")

    users = _load(seed_dir, "users")
    folders = _load(seed_dir, "folders")
    permissions = _load(seed_dir, "folderPermissions")
    records = _load(seed_dir, "records")
    batches = _load(seed_dir, "batches")
    batch_items = _load(seed_dir, "batchItems")
    audit_log = _load(seed_dir, "auditLog")

    # One hash shared by all demo users: same password, and bcrypt is slow on purpose.
    password_hash = hash_password(demo_password)

    for model in TABLES_IN_DELETE_ORDER:
        session.execute(delete(model))

    session.add_all(
        User(id=u["id"], email=u["email"], name=u["name"], password_hash=password_hash) for u in users
    )
    session.flush()
    session.add_all(
        Folder(
            id=f["id"], name=f["name"], type=f["type"], owner_id=f["ownerId"], created_at=_dt(f["createdAt"])
        )
        for f in folders
    )
    session.flush()
    session.add_all(
        FolderPermission(folder_id=p["folderId"], user_id=p["userId"], role=p["role"]) for p in permissions
    )
    session.add_all(
        LedgerRecord(
            id=r["id"],
            folder_id=r["folderId"],
            name=r["name"],
            value_cents=r["valueCents"],
            currency=r["currency"],
            status=r["status"],
            fields=r["fields"],
            version=r["version"],
            created_at=_dt(r["updatedAt"]),
            updated_at=_dt(r["updatedAt"]),
        )
        for r in records
    )
    session.flush()
    session.add_all(
        Batch(
            id=b["id"],
            folder_id=b["folderId"],
            created_by=b["createdBy"],
            status=b["status"],
            instruction=b["instruction"],
            idempotency_key=b.get("idempotencyKey"),
            created_at=_dt(b["createdAt"]),
            applied_at=_dt(b.get("appliedAt")),
        )
        for b in batches
    )
    session.flush()
    session.add_all(
        BatchItem(
            batch_id=i["batchId"],
            record_id=i["recordId"],
            # The JSON keeps the camelCase field name; the column is snake_case.
            field="value_cents" if i["field"] == "valueCents" else i["field"],
            before=i["before"],
            after=i["after"],
            expected_version=i["expectedVersion"],
            result=i.get("result"),
        )
        for i in batch_items
    )
    session.add_all(
        AuditLog(
            id=a["id"],
            user_id=a["userId"],
            action=a["action"],
            batch_id=a.get("batchId"),
            details=a["details"],
            at=_dt(a["at"]),
        )
        for a in audit_log
    )
    session.flush()

    return {
        "users": len(users),
        "folders": len(folders),
        "permissions": len(permissions),
        "records": len(records),
        "batches": len(batches),
        "batch_items": len(batch_items),
        "audit_log": len(audit_log),
    }


def main() -> int:
    settings = get_settings()
    if settings.seed_demo_password is None:
        print(
            "SEED_DEMO_PASSWORD is not set. Copy backend/.env.example to backend/.env and set it.",
            file=sys.stderr,
        )
        return 1

    make_session = session_factory(get_engine())
    try:
        with make_session.begin() as session:
            counts = seed(session, settings.data_dir / "seed", settings.seed_demo_password.get_secret_value())
    except SeedError as exc:
        print(f"Seed failed: {exc}", file=sys.stderr)
        return 1

    print("Seeded " + " ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
