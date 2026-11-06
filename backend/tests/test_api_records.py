"""Folder and record endpoints, with per-user permissions.

Sample data: Alice owns Q3 Invoices and Product Catalog. Bob owns his own folder and is an
editor on Q3 Invoices. Carol is a viewer on Q3 Invoices only.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ledgerly.db.models import AuditLog

Headers = Callable[[str], dict[str, str]]


# ---------- Folders ----------
@pytest.mark.parametrize(
    ("user", "expected"),
    [
        ("alice", {"Product Catalog": "owner", "Q3 2026 Invoices": "owner"}),
        ("bob", {"Bob's Consulting Invoices": "owner", "Q3 2026 Invoices": "editor"}),
        ("carol", {"Q3 2026 Invoices": "viewer"}),
    ],
)
def test_each_user_sees_only_their_folders(
    client: TestClient, auth_headers: Headers, user: str, expected: dict[str, str]
) -> None:
    folders = client.get("/api/folders", headers=auth_headers(user)).json()
    assert {f["name"]: f["role"] for f in folders} == expected


def test_folder_without_access_is_404_not_403(client: TestClient, auth_headers: Headers) -> None:
    # Alice must not learn that Bob's folder exists.
    hidden = client.get("/api/folders/fld_bob_invoices", headers=auth_headers("alice"))
    missing = client.get("/api/folders/fld_does_not_exist", headers=auth_headers("alice"))

    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json() == {"detail": "Folder not found"}


def test_records_of_hidden_folder_are_404(client: TestClient, auth_headers: Headers) -> None:
    response = client.get("/api/folders/fld_bob_invoices/records", headers=auth_headers("alice"))
    assert response.status_code == 404


def test_folder_endpoints_require_login(client: TestClient) -> None:
    assert client.get("/api/folders").status_code == 401
    assert client.get("/api/folders/fld_q3_invoices/records").status_code == 401


# ---------- Listing records ----------
def test_list_records_returns_all_40_demo_invoices(client: TestClient, auth_headers: Headers) -> None:
    page = client.get(
        "/api/folders/fld_q3_invoices/records", params={"limit": 500}, headers=auth_headers("carol")
    ).json()

    assert page["total"] == 40
    assert len(page["items"]) == 40
    first = page["items"][0]
    assert set(first) == {
        "id",
        "folderId",
        "name",
        "valueCents",
        "currency",
        "status",
        "fields",
        "version",
        "updatedAt",
    }


def test_paging_is_stable_and_complete(client: TestClient, auth_headers: Headers) -> None:
    ids: list[str] = []
    for offset in (0, 15, 30):
        page = client.get(
            "/api/folders/fld_q3_invoices/records",
            params={"limit": 15, "offset": offset},
            headers=auth_headers("alice"),
        ).json()
        ids += [r["id"] for r in page["items"]]

    assert len(ids) == 40
    assert len(set(ids)) == 40


def test_status_filter(client: TestClient, auth_headers: Headers) -> None:
    page = client.get(
        "/api/folders/fld_q3_invoices/records", params={"status": "overdue"}, headers=auth_headers("alice")
    ).json()

    assert page["total"] > 0
    assert all(r["status"] == "overdue" for r in page["items"])


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"offset": -1}])
def test_bad_paging_params_are_422(client: TestClient, auth_headers: Headers, params: dict[str, int]) -> None:
    response = client.get("/api/folders/fld_q3_invoices/records", params=params, headers=auth_headers("alice"))
    assert response.status_code == 422


# ---------- Reading one record ----------
def test_get_record(client: TestClient, auth_headers: Headers) -> None:
    record = client.get("/api/records/rec_inv_012", headers=auth_headers("carol")).json()
    assert record["valueCents"] == 1235


def test_record_in_hidden_folder_is_404(client: TestClient, auth_headers: Headers) -> None:
    response = client.get("/api/records/rec_bob_001", headers=auth_headers("alice"))
    assert response.status_code == 404
    assert response.json() == {"detail": "Record not found"}


# ---------- Editing one record ----------
def test_editor_can_update_and_version_increases(
    client: TestClient, auth_headers: Headers, seeded: sessionmaker[Session]
) -> None:
    response = client.patch(
        "/api/records/rec_inv_001", json={"version": 1, "valueCents": 5000}, headers=auth_headers("bob")
    )

    assert response.status_code == 200
    assert response.json()["valueCents"] == 5000
    assert response.json()["version"] == 2

    with seeded() as session:
        entry = session.scalars(select(AuditLog).where(AuditLog.action == "record.update")).one()
    assert entry.user_id == "usr_bob"
    assert entry.details["recordId"] == "rec_inv_001"
    assert entry.details["after"] == {"value_cents": 5000}


def test_viewer_cannot_update(client: TestClient, auth_headers: Headers) -> None:
    response = client.patch(
        "/api/records/rec_inv_001", json={"version": 1, "valueCents": 1}, headers=auth_headers("carol")
    )

    assert response.status_code == 403
    assert "editor" in response.json()["detail"]


def test_stale_version_is_409_and_nothing_changes(client: TestClient, auth_headers: Headers) -> None:
    first = client.patch(
        "/api/records/rec_inv_002", json={"version": 1, "valueCents": 111}, headers=auth_headers("alice")
    )
    assert first.status_code == 200

    # Bob still has version 1 loaded: his write must be rejected, not overwrite Alice's.
    stale = client.patch(
        "/api/records/rec_inv_002", json={"version": 1, "valueCents": 999}, headers=auth_headers("bob")
    )
    assert stale.status_code == 409

    current = client.get("/api/records/rec_inv_002", headers=auth_headers("alice")).json()
    assert current["valueCents"] == 111
    assert current["version"] == 2


@pytest.mark.parametrize(
    ("body", "status_code"),
    [
        ({"version": 1, "valueCents": -5}, 422),
        ({"version": 1, "status": "archived"}, 422),  # product status on an invoice
        ({"version": 0, "valueCents": 5}, 422),
        ({"valueCents": 5}, 422),  # version is required
    ],
)
def test_invalid_updates_are_rejected(
    client: TestClient, auth_headers: Headers, body: dict[str, object], status_code: int
) -> None:
    response = client.patch("/api/records/rec_inv_003", json=body, headers=auth_headers("alice"))
    assert response.status_code == status_code


def test_empty_update_changes_nothing(client: TestClient, auth_headers: Headers) -> None:
    response = client.patch("/api/records/rec_inv_004", json={"version": 1}, headers=auth_headers("alice"))

    assert response.status_code == 200
    assert response.json()["version"] == 1


def test_datetimes_are_utc_with_timezone(client: TestClient, auth_headers: Headers) -> None:
    folder = client.get("/api/folders/fld_q3_invoices", headers=auth_headers("alice")).json()
    record = client.get("/api/records/rec_inv_001", headers=auth_headers("alice")).json()

    assert folder["createdAt"] == "2026-07-01T09:00:00Z"
    assert record["updatedAt"].endswith("Z")


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}
