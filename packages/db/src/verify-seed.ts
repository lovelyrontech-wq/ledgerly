// Checks the database matches the sample data. Exits non-zero on any mismatch.
// Run: npm run verify -w @ledgerly/db

import bcrypt from "bcryptjs";
import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

const expected = {
  users: 3,
  folders: 3,
  records: 63,
  byFolder: { fld_q3_invoices: 40, fld_products: 15, fld_bob_invoices: 8 } as Record<string, number>,
  batchItems: 3,
};

async function main() {
  const failures: string[] = [];
  const check = (label: string, actual: number, want: number) => {
    const ok = actual === want;
    console.log(`${ok ? "PASS" : "FAIL"}  ${label}: ${actual} (expected ${want})`);
    if (!ok) failures.push(label);
  };

  check("users", await prisma.user.count(), expected.users);
  check("folders", await prisma.folder.count(), expected.folders);
  check("records", await prisma.ledgerRecord.count(), expected.records);

  const grouped = await prisma.ledgerRecord.groupBy({ by: ["folderId"], _count: { _all: true } });
  for (const [folderId, want] of Object.entries(expected.byFolder)) {
    const actual = grouped.find((g) => g.folderId === folderId)?._count._all ?? 0;
    check(`records in ${folderId}`, actual, want);
  }

  check("batch items", await prisma.batchItem.count(), expected.batchItems);

  // The seeded batch must line up with the records it changed.
  const items = await prisma.batchItem.findMany({ include: { record: true } });
  const mismatched = items.filter(
    (i) => i.record.valueCents !== i.after || i.record.version !== i.expectedVersion + 1,
  );
  check("seed batch items match record values and versions", mismatched.length, 0);

  // Demo logins: every user's hash must match SEED_DEMO_PASSWORD from .env, and reject a wrong password.
  const demoPassword = process.env.SEED_DEMO_PASSWORD;
  if (demoPassword) {
    const users = await prisma.user.findMany();
    let badLogins = 0;
    for (const u of users) {
      const rightOk = await bcrypt.compare(demoPassword, u.passwordHash);
      const wrongOk = await bcrypt.compare(`${demoPassword}-wrong`, u.passwordHash);
      if (!rightOk || wrongOk) badLogins++;
    }
    check("demo logins accept SEED_DEMO_PASSWORD and reject a wrong one", badLogins, 0);
  } else {
    console.log("SKIP  demo logins: SEED_DEMO_PASSWORD not set");
  }

  if (failures.length > 0) {
    console.error(`\n${failures.length} check(s) failed.`);
    process.exitCode = 1;
  } else {
    console.log("\nAll checks passed.");
  }
}

main().finally(() => prisma.$disconnect());
