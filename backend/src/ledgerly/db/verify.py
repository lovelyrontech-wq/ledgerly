"""Check the database matches the sample data. Exits non-zero on any mismatch.

Run (from backend/):  uv run python -m ledgerly.db.verify
"""

from __future__ import annotations

import sys

import bcrypt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ledgerly.config import get_settings
from ledgerly.db.models import BatchItem, Folder, LedgerRecord, User
from ledgerly.db.session import get_engine, session_factory

EXPECTED_RECORDS_BY_FOLDER = {"fld_q3_invoices": 40, "fld_products": 15, "fld_bob_invoices": 8}


def run_checks(session: Session, demo_password: str | None) -> list[tuple[str, bool, str]]:
    """Return (label, passed, detail) for each check."""
    results: list[tuple[str, bool, str]] = []

    def check(label: str, actual: int, want: int) -> None:
        results.append((label, actual == want, f"{actual} (expected {want})"))

    check("users", session.scalar(select(func.count()).select_from(User)) or 0, 3)
    check("folders", session.scalar(select(func.count()).select_from(Folder)) or 0, 3)
    check("records", session.scalar(select(func.count()).select_from(LedgerRecord)) or 0, 63)

    rows = session.execute(select(LedgerRecord.folder_id, func.count()).group_by(LedgerRecord.folder_id)).all()
    by_folder = {folder_id: count for folder_id, count in rows}
    for folder_id, want in EXPECTED_RECORDS_BY_FOLDER.items():
        check(f"records in {folder_id}", by_folder.get(folder_id, 0), want)

    items = session.scalars(select(BatchItem)).all()
    check("batch items", len(items), 3)
    mismatched = [
        i for i in items if i.record.value_cents != i.after or i.record.version != i.expected_version + 1
    ]
    check("seed batch items match record values and versions", len(mismatched), 0)

    if demo_password:
        bad = 0
        for user in session.scalars(select(User)):
            hashed = user.password_hash.encode("utf-8")
            right = bcrypt.checkpw(demo_password.encode("utf-8"), hashed)
            wrong = bcrypt.checkpw((demo_password + "-wrong").encode("utf-8"), hashed)
            if not right or wrong:
                bad += 1
        check("demo logins accept SEED_DEMO_PASSWORD and reject a wrong one", bad, 0)

    return results


def main() -> int:
    settings = get_settings()
    password = settings.seed_demo_password.get_secret_value() if settings.seed_demo_password else None
    with session_factory(get_engine())() as session:
        results = run_checks(session, password)

    for label, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {label}: {detail}")
    if password is None:
        print("SKIP  demo logins: SEED_DEMO_PASSWORD not set")

    failed = [r for r in results if not r[1]]
    print(f"\n{len(failed)} check(s) failed." if failed else "\nAll checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
