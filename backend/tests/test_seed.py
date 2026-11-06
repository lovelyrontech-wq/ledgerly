"""Seed loads the sample data correctly, can be re-run, and the database enforces its rules."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ledgerly.db.models import FolderPermission, LedgerRecord, User
from ledgerly.db.seed import SeedError, seed
from ledgerly.db.verify import run_checks
from tests.conftest import SEED_DIR, TEST_PASSWORD


def _seed(make_session: sessionmaker[Session], password: str = TEST_PASSWORD) -> dict[str, int]:
    with make_session.begin() as session:
        return seed(session, SEED_DIR, password)


def test_seed_loads_all_sample_data(make_session: sessionmaker[Session]) -> None:
    counts = _seed(make_session)

    assert counts == {
        "users": 3,
        "folders": 3,
        "permissions": 2,
        "records": 63,
        "batches": 1,
        "batch_items": 3,
        "audit_log": 2,
    }
    with make_session() as session:
        failed = [label for label, passed, _ in run_checks(session, TEST_PASSWORD) if not passed]
    assert failed == []


def test_seed_is_safe_to_rerun(make_session: sessionmaker[Session]) -> None:
    _seed(make_session)
    _seed(make_session)

    with make_session() as session:
        assert session.scalar(select(func.count()).select_from(LedgerRecord)) == 63
        assert session.scalar(select(func.count()).select_from(User)) == 3


def test_demo_folder_edge_cases_are_present(make_session: sessionmaker[Session]) -> None:
    _seed(make_session)

    with make_session() as session:
        values = {r.id: r.value_cents for r in session.scalars(select(LedgerRecord))}
    assert values["rec_inv_005"] == 0  # zero stays zero
    assert values["rec_inv_012"] == 1235  # 12.35 -> 13.585 at +10%: rounding case
    assert values["rec_inv_023"] == 99_999_999  # very large value


def test_short_password_is_rejected_and_nothing_is_written(make_session: sessionmaker[Session]) -> None:
    with pytest.raises(SeedError, match="at least 8"), make_session.begin() as session:
        seed(session, SEED_DIR, "short")

    with make_session() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


def test_missing_seed_file_gives_clear_error(make_session: sessionmaker[Session], tmp_path: Path) -> None:
    with pytest.raises(SeedError, match="Missing seed file"), make_session.begin() as session:
        seed(session, tmp_path, TEST_PASSWORD)


def test_failed_seed_keeps_existing_data(make_session: sessionmaker[Session], tmp_path: Path) -> None:
    _seed(make_session)

    # users.json present but the rest missing: seed fails partway and must roll back.
    (tmp_path / "users.json").write_text((SEED_DIR / "users.json").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(SeedError), make_session.begin() as session:
        seed(session, tmp_path, TEST_PASSWORD)

    with make_session() as session:
        assert session.scalar(select(func.count()).select_from(LedgerRecord)) == 63


def test_foreign_keys_are_enforced(make_session: sessionmaker[Session]) -> None:
    _seed(make_session)

    with pytest.raises(IntegrityError), make_session.begin() as session:
        session.add(
            LedgerRecord(
                folder_id="fld_does_not_exist",
                name="orphan",
                value_cents=100,
                currency="USD",
                status="draft",
                fields={},
            )
        )


def test_invalid_share_role_is_rejected(make_session: sessionmaker[Session]) -> None:
    _seed(make_session)

    with pytest.raises(IntegrityError), make_session.begin() as session:
        session.add(FolderPermission(folder_id="fld_products", user_id="usr_carol", role="admin"))


def test_negative_value_is_rejected(make_session: sessionmaker[Session]) -> None:
    _seed(make_session)

    with pytest.raises(IntegrityError), make_session.begin() as session:
        record = session.get(LedgerRecord, "rec_inv_001")
        assert record is not None
        record.value_cents = -1
