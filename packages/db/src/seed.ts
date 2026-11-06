// Loads packages/db/seed/*.json into the database.
// Safe to re-run: it clears the tables first, then inserts everything in one transaction.
// Run: npm run db:seed (from the repo root)

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import bcrypt from "bcryptjs";
import { PrismaClient } from "@prisma/client";

const seedDir = join(dirname(fileURLToPath(import.meta.url)), "..", "seed");

function load<T>(name: string): T {
  return JSON.parse(readFileSync(join(seedDir, `${name}.json`), "utf8")) as T;
}

type SeedUser = { id: string; email: string; name: string };
type SeedFolder = { id: string; name: string; type: string; ownerId: string; createdAt: string };
type SeedPermission = { folderId: string; userId: string; role: string };
type SeedRecord = {
  id: string; folderId: string; name: string; valueCents: number; currency: string;
  status: string; fields: Record<string, unknown>; version: number; updatedAt: string;
};
type SeedBatch = {
  id: string; folderId: string; createdBy: string; status: string; instruction: string;
  idempotencyKey: string; createdAt: string; appliedAt: string;
};
type SeedBatchItem = {
  batchId: string; recordId: string; field: string; before: number; after: number;
  expectedVersion: number; result: string;
};
type SeedAudit = {
  id: string; userId: string; action: string; batchId: string; at: string;
  details: Record<string, unknown>;
};

const users = load<SeedUser[]>("users");
const folders = load<SeedFolder[]>("folders");
const permissions = load<SeedPermission[]>("folderPermissions");
const records = load<SeedRecord[]>("records");
const batches = load<SeedBatch[]>("batches");
const batchItems = load<SeedBatchItem[]>("batchItems");
const auditLog = load<SeedAudit[]>("auditLog");

// The demo password comes from .env (never committed), so it is not stored in the repo.
function requireDemoPassword(): string {
  const value = process.env.SEED_DEMO_PASSWORD;
  if (!value || value.length < 8) {
    console.error(
      "SEED_DEMO_PASSWORD is not set (or is shorter than 8 characters). " +
        "Copy .env.example to packages/db/.env and set it.",
    );
    process.exit(1);
  }
  return value;
}
const demoPassword = requireDemoPassword();

const prisma = new PrismaClient();

async function main() {
  // Hash outside the transaction: bcrypt is slow on purpose and would hold the write lock.
  const userRows = await Promise.all(
    users.map(async (u) => ({
      id: u.id,
      email: u.email,
      name: u.name,
      passwordHash: await bcrypt.hash(demoPassword, 10),
    })),
  );

  await prisma.$transaction([
    // Delete children before parents.
    prisma.auditLog.deleteMany(),
    prisma.batchItem.deleteMany(),
    prisma.batch.deleteMany(),
    prisma.ledgerRecord.deleteMany(),
    prisma.folderPermission.deleteMany(),
    prisma.folder.deleteMany(),
    prisma.user.deleteMany(),

    prisma.user.createMany({ data: userRows }),
    prisma.folder.createMany({
      data: folders.map((f) => ({ ...f, createdAt: new Date(f.createdAt) })),
    }),
    prisma.folderPermission.createMany({ data: permissions }),
    prisma.ledgerRecord.createMany({
      data: records.map((r) => ({
        id: r.id,
        folderId: r.folderId,
        name: r.name,
        valueCents: r.valueCents,
        currency: r.currency,
        status: r.status,
        fields: r.fields as object,
        version: r.version,
        createdAt: new Date(r.updatedAt),
        updatedAt: new Date(r.updatedAt),
      })),
    }),
    prisma.batch.createMany({
      data: batches.map((b) => ({
        ...b,
        createdAt: new Date(b.createdAt),
        appliedAt: new Date(b.appliedAt),
      })),
    }),
    prisma.batchItem.createMany({ data: batchItems }),
    prisma.auditLog.createMany({
      data: auditLog.map((a) => ({ ...a, details: a.details as object, at: new Date(a.at) })),
    }),
  ]);

  console.log(
    `Seeded users=${users.length} folders=${folders.length} permissions=${permissions.length} ` +
      `records=${records.length} batches=${batches.length} batchItems=${batchItems.length} ` +
      `auditLog=${auditLog.length}`,
  );
}

main()
  .catch((err) => {
    console.error("Seed failed:", err);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());
