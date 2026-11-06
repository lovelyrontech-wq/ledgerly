"""Bulk update: preview -> apply -> undo, with approval, idempotency, and version checks.

The demo: Alice asks to raise every value in Q3 2026 Invoices (40 records) by 10%.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from ledgerly.db.models import AuditLog, Batch, utcnow
from ledgerly.services.batches import apply_percent

Headers = Callable[[str], dict[str, str]]
FOLDER = "fld_q3_invoices"


def _preview(client: TestClient, headers: dict[str, str], percent: float = 10, **extra: Any) -> Any:
    response = client.post(
        f"/api/folders/{FOLDER}/batches/preview",
        json={"percent": percent, "instruction": "update the values in this folder by 10%", **extra},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _apply(client: TestClient, headers: dict[str, str], batch: dict[str, Any], key: str = "key-0001") -> Any:
    return client.post(
        f"/api/batches/{batch['id']}/apply",
        json={"previewHash": batch["previewHash"]},
        headers={**headers, "Idempotency-Key": key},
    )


def _values(client: TestClient, headers: dict[str, str]) -> dict[str, int]:
    page = client.get(f"/api/folders/{FOLDER}/records", params={"limit": 500}, headers=headers).json()
    return {r["id"]: r["valueCents"] for r in page["items"]}


# ---------- Rounding ----------
@pytest.mark.parametrize(
    ("value", "percent", "expected"),
    [
        (1235, Decimal(10), 1359),  # 1358.5 rounds half-up
        (0, Decimal(10), 0),
        (99_999_999, Decimal(10), 109_999_999),  # 109999998.9
        (1000, Decimal(-100), 0),
        (1001, Decimal("-33.33"), 667),  # 667.3667
        (5, Decimal(-50), 3),  # 2.5 rounds half-up
    ],
)
def test_apply_percent_rounds_half_up(value: int, percent: Decimal, expected: int) -> None:
    assert apply_percent(value, percent) == expected


# ---------- Preview ----------
def test_preview_lists_all_40_records_and_changes_nothing(client: TestClient, auth_headers: Headers) -> None:
    alice = auth_headers("alice")
    before = _values(client, alice)

    batch = _preview(client, alice)

    assert batch["status"] == "pending"
    assert len(batch["items"]) == 40
    assert batch["summary"] == {"pending": 40}
    assert len(batch["previewHash"]) == 64
    item = next(i for i in batch["items"] if i["recordId"] == "rec_inv_012")
    assert (item["before"], item["after"], item["expectedVersion"]) == (1235, 1359, 1)
    assert _values(client, alice) == before  # a preview writes nothing


def test_preview_status_filter(client: TestClient, auth_headers: Headers) -> None:
    batch = _preview(client, auth_headers("alice"), status="overdue")
    assert 0 < len(batch["items"]) < 40


def test_viewer_cannot_preview(client: TestClient, auth_headers: Headers) -> None:
    response = client.post(
        f"/api/folders/{FOLDER}/batches/preview",
        json={"percent": 10, "instruction": "x"},
        headers=auth_headers("carol"),
    )
    assert response.status_code == 403


def test_preview_of_hidden_folder_is_404(client: TestClient, auth_headers: Headers) -> None:
    response = client.post(
        "/api/folders/fld_bob_invoices/batches/preview",
        json={"percent": 10, "instruction": "x"},
        headers=auth_headers("alice"),
    )
    assert response.status_code == 404


@pytest.mark.parametrize("percent", [-101, 1001, 1.234])
def test_preview_rejects_bad_percent(client: TestClient, auth_headers: Headers, percent: float) -> None:
    response = client.post(
        f"/api/folders/{FOLDER}/batches/preview",
        json={"percent": percent, "instruction": "x"},
        headers=auth_headers("alice"),
    )
    assert response.status_code == 422


def test_preview_with_no_matching_records_is_409(client: TestClient, auth_headers: Headers) -> None:
    response = client.post(
        f"/api/folders/{FOLDER}/batches/preview",
        json={"percent": 10, "instruction": "x", "status": "no-such-status"},
        headers=auth_headers("alice"),
    )
    assert response.status_code == 409


# ---------- Apply ----------
def test_apply_writes_exactly_the_preview(
    client: TestClient, auth_headers: Headers, seeded: sessionmaker[Session]
) -> None:
    alice = auth_headers("alice")
    batch = _preview(client, alice)

    response = _apply(client, alice, batch)

    assert response.status_code == 200, response.text
    applied = response.json()
    assert applied["status"] == "applied"
    assert applied["summary"] == {"applied": 40}
    assert _values(client, alice) == {i["recordId"]: i["after"] for i in batch["items"]}
    record = client.get("/api/records/rec_inv_012", headers=alice).json()
    assert record["version"] == 2

    with seeded() as session:
        actions = session.scalars(select(AuditLog.action).where(AuditLog.batch_id == batch["id"])).all()
    assert sorted(actions) == ["batch.apply", "batch.preview"]


def test_same_idempotency_key_does_not_apply_twice(client: TestClient, auth_headers: Headers) -> None:
    alice = auth_headers("alice")
    batch = _preview(client, alice)

    first = _apply(client, alice, batch, key="retry-key-1")
    values_after_first = _values(client, alice)
    second = _apply(client, alice, batch, key="retry-key-1")

    assert first.status_code == second.status_code == 200
    assert second.json()["summary"] == {"applied": 40}
    assert _values(client, alice) == values_after_first


def test_new_key_on_applied_batch_is_409(client: TestClient, auth_headers: Headers) -> None:
    alice = auth_headers("alice")
    batch = _preview(client, alice)
    assert _apply(client, alice, batch, key="key-aaaa").status_code == 200

    assert _apply(client, alice, batch, key="key-bbbb").status_code == 409


def test_key_reused_for_other_batch_is_409(client: TestClient, auth_headers: Headers) -> None:
    alice = auth_headers("alice")
    first = _preview(client, alice)
    second = _preview(client, alice, percent=5)
    assert _apply(client, alice, first, key="shared-key").status_code == 200

    assert _apply(client, alice, second, key="shared-key").status_code == 409


def test_apply_needs_idempotency_key(client: TestClient, auth_headers: Headers) -> None:
    alice = auth_headers("alice")
    batch = _preview(client, alice)
    response = client.post(
        f"/api/batches/{batch['id']}/apply", json={"previewHash": batch["previewHash"]}, headers=alice
    )
    assert response.status_code == 422


def test_wrong_preview_hash_is_409_and_writes_nothing(client: TestClient, auth_headers: Headers) -> None:
    alice = auth_headers("alice")
    batch = _preview(client, alice)
    before = _values(client, alice)

    response = _apply(client, alice, {**batch, "previewHash": "0" * 64})

    assert response.status_code == 409
    assert _values(client, alice) == before
    assert client.get(f"/api/batches/{batch['id']}", headers=alice).json()["status"] == "pending"


def test_record_changed_after_preview_is_skipped_not_overwritten(client: TestClient, auth_headers: Headers) -> None:
    alice, bob = auth_headers("alice"), auth_headers("bob")
    batch = _preview(client, alice)
    # Bob edits one record between the preview and the apply.
    assert (
        client.patch("/api/records/rec_inv_001", json={"version": 1, "valueCents": 777}, headers=bob).status_code == 200
    )

    applied = _apply(client, alice, batch).json()

    assert applied["summary"] == {"applied": 39, "skipped_changed": 1}
    skipped = next(i for i in applied["items"] if i["recordId"] == "rec_inv_001")
    assert skipped["result"] == "skipped_changed"
    assert skipped["error"]
    assert client.get("/api/records/rec_inv_001", headers=alice).json()["valueCents"] == 777


def test_viewer_cannot_apply(client: TestClient, auth_headers: Headers) -> None:
    batch = _preview(client, auth_headers("alice"))
    assert _apply(client, auth_headers("carol"), batch).status_code == 403


def test_expired_preview_cannot_be_applied(
    client: TestClient, auth_headers: Headers, seeded: sessionmaker[Session]
) -> None:
    alice = auth_headers("alice")
    batch = _preview(client, alice)
    with seeded.begin() as session:
        session.execute(update(Batch).where(Batch.id == batch["id"]).values(expires_at=utcnow() - timedelta(minutes=1)))

    response = _apply(client, alice, batch)

    assert response.status_code == 409
    assert "expired" in response.json()["detail"]
    assert client.get(f"/api/batches/{batch['id']}", headers=alice).json()["status"] == "expired"


# ---------- Undo ----------
def test_undo_restores_old_values(client: TestClient, auth_headers: Headers) -> None:
    alice = auth_headers("alice")
    original = _values(client, alice)
    batch = _preview(client, alice)
    _apply(client, alice, batch)

    response = client.post(f"/api/batches/{batch['id']}/undo", headers=alice)

    assert response.status_code == 200
    assert response.json()["status"] == "undone"
    assert response.json()["summary"] == {"undone": 40}
    assert _values(client, alice) == original
    assert client.get("/api/records/rec_inv_012", headers=alice).json()["version"] == 3


def test_undo_skips_records_edited_after_apply(client: TestClient, auth_headers: Headers) -> None:
    alice, bob = auth_headers("alice"), auth_headers("bob")
    batch = _preview(client, alice)
    _apply(client, alice, batch)
    assert (
        client.patch("/api/records/rec_inv_002", json={"version": 2, "valueCents": 4242}, headers=bob).status_code
        == 200
    )

    undone = client.post(f"/api/batches/{batch['id']}/undo", headers=alice).json()

    assert undone["summary"] == {"undone": 39, "undo_skipped": 1}
    assert client.get("/api/records/rec_inv_002", headers=alice).json()["valueCents"] == 4242


def test_undo_twice_is_409(client: TestClient, auth_headers: Headers) -> None:
    alice = auth_headers("alice")
    batch = _preview(client, alice)
    _apply(client, alice, batch)
    assert client.post(f"/api/batches/{batch['id']}/undo", headers=alice).status_code == 200

    assert client.post(f"/api/batches/{batch['id']}/undo", headers=alice).status_code == 409


def test_undo_pending_batch_is_409(client: TestClient, auth_headers: Headers) -> None:
    alice = auth_headers("alice")
    batch = _preview(client, alice)
    assert client.post(f"/api/batches/{batch['id']}/undo", headers=alice).status_code == 409


# ---------- Reading ----------
def test_batch_in_hidden_folder_is_404(client: TestClient, auth_headers: Headers) -> None:
    response = client.get("/api/batches/bat_seed_001", headers=auth_headers("bob"))
    assert response.status_code == 404
    assert response.json() == {"detail": "Batch not found"}


def test_seed_batch_is_readable_by_owner(client: TestClient, auth_headers: Headers) -> None:
    batch = client.get("/api/batches/bat_seed_001", headers=auth_headers("alice")).json()
    assert batch["status"] == "applied"
    assert batch["summary"] == {"applied": 3}
