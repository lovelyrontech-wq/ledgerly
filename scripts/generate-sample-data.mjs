// Generates the sample data in packages/db/seed/*.json.
// Deterministic: the same seed always gives the same records, so demos and tests are repeatable.
// Run: node scripts/generate-sample-data.mjs

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = join(root, "packages", "db", "seed");
mkdirSync(outDir, { recursive: true });

// Small seeded PRNG (mulberry32) so output is stable across runs.
function rng(seed) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = rng(42);
const pick = (arr) => arr[Math.floor(rand() * arr.length)];
const between = (min, max) => Math.floor(rand() * (max - min + 1)) + min;
const pad = (n, w) => String(n).padStart(w, "0");

const BASE_TIME = Date.parse("2026-07-01T09:00:00Z");
const isoAt = (dayOffset) => new Date(BASE_TIME + dayOffset * 86_400_000).toISOString();

// ---------- Users ----------
// No passwords here. The seed script sets every demo user's password from SEED_DEMO_PASSWORD in .env.
const users = [
  { id: "usr_alice", email: "alice@ledgerly.test", name: "Alice Owner" },
  { id: "usr_bob", email: "bob@ledgerly.test", name: "Bob Member" },
  { id: "usr_carol", email: "carol@ledgerly.test", name: "Carol Viewer" },
];

// ---------- Folders ----------
const folders = [
  { id: "fld_q3_invoices", name: "Q3 2026 Invoices", type: "invoice", ownerId: "usr_alice", createdAt: isoAt(0) },
  { id: "fld_products", name: "Product Catalog", type: "product", ownerId: "usr_alice", createdAt: isoAt(1) },
  { id: "fld_bob_invoices", name: "Bob's Consulting Invoices", type: "invoice", ownerId: "usr_bob", createdAt: isoAt(2) },
];

// Per-user permissions. Owners get full access implicitly.
// Carol can view Alice's invoices but not edit, which tests read-only access through the agent.
const folderPermissions = [
  { folderId: "fld_q3_invoices", userId: "usr_bob", role: "editor" },
  { folderId: "fld_q3_invoices", userId: "usr_carol", role: "viewer" },
];

// ---------- Records ----------
// Money is stored as integer cents (valueCents) to avoid floating-point errors in bulk % changes.
// `version` increments on every write; apply_bulk_update uses it to detect records changed since preview.
const customers = [
  "Acme Corp", "Globex Ltd", "Initech", "Umbrella Health", "Stark Supplies",
  "Wayne Logistics", "Hooli", "Vandelay Imports", "Soylent Foods", "Wonka Retail",
];
const invoiceStatuses = ["draft", "sent", "sent", "sent", "paid", "overdue"];

const records = [];

// 40 invoices: the demo folder for "update the values in this folder by 10%".
for (let i = 1; i <= 40; i++) {
  const issued = between(0, 85);
  records.push({
    id: `rec_inv_${pad(i, 3)}`,
    folderId: "fld_q3_invoices",
    name: `INV-2026-${pad(1000 + i, 4)}`,
    valueCents: between(250_00, 12_500_00) + between(0, 99),
    currency: "USD",
    status: pick(invoiceStatuses),
    fields: {
      customer: pick(customers),
      issuedAt: isoAt(issued).slice(0, 10),
      dueAt: isoAt(issued + 30).slice(0, 10),
    },
    version: 1,
    updatedAt: isoAt(issued),
  });
}

// Edge cases mixed into the demo folder so the preview has something worth showing.
Object.assign(records[4], { valueCents: 0, status: "draft" }); // zero stays zero
Object.assign(records[11], { valueCents: 1235 }); // 12.35 * 1.10 = 13.585, tests rounding rule
Object.assign(records[22], { valueCents: 999_999_99 }); // very large value

// 15 products.
const productNames = [
  "Standing Desk", "Ergonomic Chair", "Monitor Arm", "USB-C Dock", "Mechanical Keyboard",
  "Wireless Mouse", "Desk Lamp", "Cable Tray", "Laptop Stand", "Webcam HD",
  "Noise-Cancelling Headset", "Footrest", "Whiteboard", "Document Scanner", "Label Printer",
];
productNames.forEach((name, idx) => {
  const i = idx + 1;
  records.push({
    id: `rec_prd_${pad(i, 3)}`,
    folderId: "fld_products",
    name,
    valueCents: between(19, 899) * 100 + 99, // retail-style prices like 249.99
    currency: "USD",
    status: i % 7 === 0 ? "archived" : "active",
    fields: {
      sku: `SKU-${pad(5000 + i, 5)}`,
      stock: between(0, 250),
      category: pick(["Furniture", "Electronics", "Accessories", "Office"]),
    },
    version: 1,
    updatedAt: isoAt(between(0, 60)),
  });
});

// 8 invoices owned by Bob. Alice has no access, which tests that the agent cannot see them.
for (let i = 1; i <= 8; i++) {
  const issued = between(0, 85);
  records.push({
    id: `rec_bob_${pad(i, 3)}`,
    folderId: "fld_bob_invoices",
    name: `BOB-2026-${pad(i, 3)}`,
    valueCents: between(500_00, 4_000_00),
    currency: "EUR",
    status: pick(invoiceStatuses),
    fields: {
      customer: pick(customers),
      issuedAt: isoAt(issued).slice(0, 10),
      dueAt: isoAt(issued + 14).slice(0, 10),
    },
    version: 1,
    updatedAt: isoAt(issued),
  });
}

// ---------- One past batch, so undo and the audit log have history on first run ----------
const pastBatchRecords = records.filter((r) => r.folderId === "fld_products").slice(0, 3);
const batches = [
  {
    id: "bat_seed_001",
    folderId: "fld_products",
    createdBy: "usr_alice",
    status: "applied",
    instruction: "increase prices of the first 3 products by 5%",
    idempotencyKey: "seed-idem-001",
    createdAt: isoAt(70),
    appliedAt: isoAt(70),
  },
];
const batchItems = pastBatchRecords.map((r) => {
  const before = r.valueCents;
  const after = Math.round(before * 1.05);
  r.valueCents = after;
  r.version = 2;
  r.updatedAt = isoAt(70);
  return {
    batchId: "bat_seed_001", recordId: r.id, field: "valueCents",
    before, after, expectedVersion: 1, result: "applied",
  };
});
const auditLog = [
  { id: "aud_001", userId: "usr_alice", action: "batch.preview", batchId: "bat_seed_001", at: isoAt(70), details: { recordCount: 3 } },
  { id: "aud_002", userId: "usr_alice", action: "batch.apply", batchId: "bat_seed_001", at: isoAt(70), details: { applied: 3, failed: 0 } },
];

// ---------- Write ----------
const files = { users, folders, folderPermissions, records, batches, batchItems, auditLog };
for (const [name, data] of Object.entries(files)) {
  writeFileSync(join(outDir, `${name}.json`), JSON.stringify(data, null, 2) + "\n");
}

const count = (f) => records.filter((r) => r.folderId === f).length;
console.log(`Wrote ${Object.keys(files).length} files to ${outDir}`);
console.log(`users=${users.length} folders=${folders.length} records=${records.length} ` +
  `(q3_invoices=${count("fld_q3_invoices")}, products=${count("fld_products")}, bob_invoices=${count("fld_bob_invoices")})`);
