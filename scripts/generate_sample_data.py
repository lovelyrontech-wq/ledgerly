"""Generate the sample data in data/seed/*.json.

Deterministic: a seeded PRNG means the same records every run, so demos and tests are repeatable.
The PRNG (mulberry32) and the order of random draws match the original JS generator exactly,
so this script reproduces the committed JSON byte for byte.

No passwords are written. The backend seed sets every demo user's password from
SEED_DEMO_PASSWORD in backend/.env.

Run from the repo root:  python scripts/generate_sample_data.py
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "seed"

MASK32 = 0xFFFFFFFF


def mulberry32(seed: int):
    """Same output as the common JS mulberry32, using explicit 32-bit unsigned arithmetic."""
    state = seed & MASK32

    def imul(a: int, b: int) -> int:
        return (a * b) & MASK32

    def next_float() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & MASK32
        t = imul(state ^ (state >> 15), 1 | state)
        t = ((t + imul(t ^ (t >> 7), 61 | t)) & MASK32) ^ t
        return ((t ^ (t >> 14)) & MASK32) / 4294967296

    return next_float


rand = mulberry32(42)


def pick(items: list[Any]) -> Any:
    return items[math.floor(rand() * len(items))]


def between(lo: int, hi: int) -> int:
    return math.floor(rand() * (hi - lo + 1)) + lo


def round_half_up(x: float) -> int:
    """JS Math.round semantics (Python's round() uses banker's rounding)."""
    return math.floor(x + 0.5)


BASE_TIME = datetime(2026, 7, 1, 9, 0, 0, tzinfo=UTC)


def iso_at(day_offset: int) -> str:
    """ISO timestamp in the same format as JS Date.toISOString(): 2026-07-01T09:00:00.000Z."""
    dt = BASE_TIME + timedelta(days=day_offset)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------- Users ----------
users = [
    {"id": "usr_alice", "email": "alice@ledgerly.test", "name": "Alice Owner"},
    {"id": "usr_bob", "email": "bob@ledgerly.test", "name": "Bob Member"},
    {"id": "usr_carol", "email": "carol@ledgerly.test", "name": "Carol Viewer"},
]

# ---------- Folders ----------
folders = [
    {
        "id": "fld_q3_invoices",
        "name": "Q3 2026 Invoices",
        "type": "invoice",
        "ownerId": "usr_alice",
        "createdAt": iso_at(0),
    },
    {
        "id": "fld_products",
        "name": "Product Catalog",
        "type": "product",
        "ownerId": "usr_alice",
        "createdAt": iso_at(1),
    },
    {
        "id": "fld_bob_invoices",
        "name": "Bob's Consulting Invoices",
        "type": "invoice",
        "ownerId": "usr_bob",
        "createdAt": iso_at(2),
    },
]

# Owners get full access implicitly. Carol can view Alice's invoices but not edit.
folder_permissions = [
    {"folderId": "fld_q3_invoices", "userId": "usr_bob", "role": "editor"},
    {"folderId": "fld_q3_invoices", "userId": "usr_carol", "role": "viewer"},
]

# ---------- Records ----------
# Money is integer cents. `version` increments on every write; bulk apply uses it to
# detect records changed since the preview.
customers = [
    "Acme Corp",
    "Globex Ltd",
    "Initech",
    "Umbrella Health",
    "Stark Supplies",
    "Wayne Logistics",
    "Hooli",
    "Vandelay Imports",
    "Soylent Foods",
    "Wonka Retail",
]
invoice_statuses = ["draft", "sent", "sent", "sent", "paid", "overdue"]

records: list[dict[str, Any]] = []

# 40 invoices: the demo folder for "update the values in this folder by 10%".
for i in range(1, 41):
    issued = between(0, 85)
    value = between(250_00, 12_500_00) + between(0, 99)
    status = pick(invoice_statuses)
    customer = pick(customers)
    records.append(
        {
            "id": f"rec_inv_{i:03d}",
            "folderId": "fld_q3_invoices",
            "name": f"INV-2026-{1000 + i:04d}",
            "valueCents": value,
            "currency": "USD",
            "status": status,
            "fields": {
                "customer": customer,
                "issuedAt": iso_at(issued)[:10],
                "dueAt": iso_at(issued + 30)[:10],
            },
            "version": 1,
            "updatedAt": iso_at(issued),
        }
    )

# Edge cases in the demo folder so the preview has something worth showing.
records[4].update({"valueCents": 0, "status": "draft"})  # zero stays zero
records[11].update({"valueCents": 1235})  # 12.35 * 1.10 = 13.585, tests the rounding rule
records[22].update({"valueCents": 999_999_99})  # very large value

# 15 products.
product_names = [
    "Standing Desk",
    "Ergonomic Chair",
    "Monitor Arm",
    "USB-C Dock",
    "Mechanical Keyboard",
    "Wireless Mouse",
    "Desk Lamp",
    "Cable Tray",
    "Laptop Stand",
    "Webcam HD",
    "Noise-Cancelling Headset",
    "Footrest",
    "Whiteboard",
    "Document Scanner",
    "Label Printer",
]
for i, name in enumerate(product_names, start=1):
    value = between(19, 899) * 100 + 99  # retail-style prices like 249.99
    stock = between(0, 250)
    category = pick(["Furniture", "Electronics", "Accessories", "Office"])
    updated = iso_at(between(0, 60))
    records.append(
        {
            "id": f"rec_prd_{i:03d}",
            "folderId": "fld_products",
            "name": name,
            "valueCents": value,
            "currency": "USD",
            "status": "archived" if i % 7 == 0 else "active",
            "fields": {"sku": f"SKU-{5000 + i:05d}", "stock": stock, "category": category},
            "version": 1,
            "updatedAt": updated,
        }
    )

# 8 invoices owned by Bob. Alice has no access: tests that the agent cannot see them.
for i in range(1, 9):
    issued = between(0, 85)
    value = between(500_00, 4_000_00)
    status = pick(invoice_statuses)
    customer = pick(customers)
    records.append(
        {
            "id": f"rec_bob_{i:03d}",
            "folderId": "fld_bob_invoices",
            "name": f"BOB-2026-{i:03d}",
            "valueCents": value,
            "currency": "EUR",
            "status": status,
            "fields": {
                "customer": customer,
                "issuedAt": iso_at(issued)[:10],
                "dueAt": iso_at(issued + 14)[:10],
            },
            "version": 1,
            "updatedAt": iso_at(issued),
        }
    )

# ---------- One past batch, so undo and the audit log have history on first run ----------
batches = [
    {
        "id": "bat_seed_001",
        "folderId": "fld_products",
        "createdBy": "usr_alice",
        "status": "applied",
        "instruction": "increase prices of the first 3 products by 5%",
        "idempotencyKey": "seed-idem-001",
        "createdAt": iso_at(70),
        "appliedAt": iso_at(70),
    }
]
batch_items = []
for r in [r for r in records if r["folderId"] == "fld_products"][:3]:
    before = r["valueCents"]
    after = round_half_up(before * 1.05)
    r.update({"valueCents": after, "version": 2, "updatedAt": iso_at(70)})
    batch_items.append(
        {
            "batchId": "bat_seed_001",
            "recordId": r["id"],
            "field": "valueCents",
            "before": before,
            "after": after,
            "expectedVersion": 1,
            "result": "applied",
        }
    )

audit_log = [
    {
        "id": "aud_001",
        "userId": "usr_alice",
        "action": "batch.preview",
        "batchId": "bat_seed_001",
        "at": iso_at(70),
        "details": {"recordCount": 3},
    },
    {
        "id": "aud_002",
        "userId": "usr_alice",
        "action": "batch.apply",
        "batchId": "bat_seed_001",
        "at": iso_at(70),
        "details": {"applied": 3, "failed": 0},
    },
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "users": users,
        "folders": folders,
        "folderPermissions": folder_permissions,
        "records": records,
        "batches": batches,
        "batchItems": batch_items,
        "auditLog": audit_log,
    }
    for name, data in files.items():
        (OUT_DIR / f"{name}.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )

    def count(folder_id: str) -> int:
        return sum(1 for r in records if r["folderId"] == folder_id)

    print(f"Wrote {len(files)} files to {OUT_DIR}")
    print(
        f"users={len(users)} folders={len(folders)} records={len(records)} "
        f"(q3_invoices={count('fld_q3_invoices')}, products={count('fld_products')}, "
        f"bob_invoices={count('fld_bob_invoices')})"
    )


if __name__ == "__main__":
    main()
