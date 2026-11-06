# Ledgerly

A mini SaaS app with folders of records (invoices, products) and an in-app agent that previews bulk changes, applies them only after approval, and can undo them.

- Use case and guardrails: [docs/USE_CASE.md](docs/USE_CASE.md)
- Architecture diagrams: [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)

## Requirements

- Node.js 20 or later (developed on Node 24, npm 11)
- Ollama, from step 5 onward

## Setup

```bash
npm install

# npm 11 blocks package install scripts by default. Prisma needs its script to download
# its database engine. The allowed packages are listed under "allowScripts" in package.json.
npm approve-scripts prisma @prisma/client @prisma/engines esbuild
npm rebuild prisma @prisma/client @prisma/engines esbuild

# Settings. The SQLite file is created at packages/db/prisma/dev.db.
# Edit packages/db/.env and set SEED_DEMO_PASSWORD (used for all demo logins).
# .env is git-ignored: never commit it. Only .env.example is committed.
cp .env.example packages/db/.env

# Create the database from the schema, generate the Prisma client, and load the sample data.
npm run db:migrate -- --name init

# Check the database contents.
npm run verify -w @ledgerly/db
```

## Database commands

| Command | What it does |
|---------|--------------|
| `npm run db:migrate -- --name <name>` | After editing `schema.prisma`: create a migration and apply it |
| `npm run db:seed` | Reload the sample data. Clears the tables first, so it is safe to re-run |
| `npm run db:reset` | Drop the database, re-apply all migrations, and seed |
| `npm run db:studio` | Open Prisma Studio to browse the data in the browser |
| `npm run sample-data` | Regenerate the JSON in `packages/db/seed/` from `scripts/generate-sample-data.mjs` |
| `npm run verify -w @ledgerly/db` | Check record counts and the seeded batch |

Always pass `--name` to `db:migrate`. Without it, Prisma waits for a name to be typed, which hangs in scripts and CI.

## Demo logins

All demo users log in with the `SEED_DEMO_PASSWORD` you set in `packages/db/.env`.

| User | Email |
|------|-------|
| Alice (owner) | `alice@ledgerly.test` |
| Bob (editor on Q3 Invoices) | `bob@ledgerly.test` |
| Carol (viewer on Q3 Invoices) | `carol@ledgerly.test` |

## Switching to Postgres

In `packages/db/prisma/schema.prisma`, change `provider = "sqlite"` to `provider = "postgresql"`. Set `DATABASE_URL` to a `postgres://` URL. Delete `packages/db/prisma/migrations/` (SQLite migrations don't run on Postgres), then run `npm run db:migrate -- --name init`.
