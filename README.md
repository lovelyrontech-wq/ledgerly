# Ledgerly

A mini SaaS app with folders of records (invoices, products) and an in-app agent that previews bulk changes, applies them only after approval, and can undo them.

- Use case and guardrails: [docs/USE_CASE.md](docs/USE_CASE.md)
- Architecture diagrams: [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)

| Part | Where | Stack |
|------|-------|-------|
| Backend: API, MCP server, agent, RAG, tracing | `backend/` | Python 3.12+, FastAPI, SQLAlchemy, Alembic |
| Web UI | `apps/web/` | Next.js (TypeScript), UI only (step 3) |
| Sample data and help docs | `data/` | JSON and Markdown |

## Requirements

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/) for Python packages
- Node.js 20+ for the web UI (from step 3)
- Ollama (from step 5)

**Run the whole app locally (all four servers):** see [docs/LOCAL_DEV.md](docs/LOCAL_DEV.md).

## Backend setup

```bash
cd backend

# Install dependencies into backend/.venv
uv sync

# Settings. Edit backend/.env and set SEED_DEMO_PASSWORD (used for all demo logins).
# backend/.env is git-ignored: never commit it. Only .env.example is committed.
cp .env.example .env

# Create the database (SQLite file at backend/dev.db) and load the sample data
uv run alembic upgrade head
uv run python -m ledgerly.db.seed

# Check the database contents
uv run python -m ledgerly.db.verify
```

## Backend commands

Run from `backend/`.

| Command | What it does |
|---------|--------------|
| `uv run alembic upgrade head` | Apply all migrations |
| `uv run alembic revision --autogenerate -m "<what changed>"` | After editing `src/ledgerly/db/models.py`: create a migration. Review it before committing |
| `uv run alembic check` | Fail if the models and migrations are out of sync |
| `uv run python -m ledgerly.db.seed` | Reload the sample data. Clears the tables first, so it is safe to re-run |
| `uv run python -m ledgerly.db.verify` | Check record counts, the seeded batch, and demo logins |
| `uv run pytest` | Run tests (each test builds a fresh database from the migrations) |
| `uv run ruff check src tests` | Lint |
| `uv run mypy src` | Type check (strict) |

From the repo root, `python scripts/generate_sample_data.py` regenerates `data/seed/*.json`. Output is always the same.

## Demo logins

All demo users log in with the `SEED_DEMO_PASSWORD` you set in `backend/.env`.

| User | Email |
|------|-------|
| Alice (owner) | `alice@ledgerly.test` |
| Bob (editor on Q3 Invoices) | `bob@ledgerly.test` |
| Carol (viewer on Q3 Invoices) | `carol@ledgerly.test` |

## Switching to Postgres

1. Add a driver: `uv add "psycopg[binary]"`.
2. Set `DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/ledgerly` in `backend/.env`.
3. Run `uv run alembic upgrade head` and the seed.

The same migrations work on both databases (JSON columns become `JSONB` on Postgres).

## Roadmap

1. ~~Workspace, database schema, sample data~~ (done)
2. REST API with permissions and preview / apply / undo, with integration tests
3. Next.js UI: login, folders, records, preview/approve dialog
4. MCP server wrapping the API
5. Agent on Ollama
6. Help-doc search (RAG)
7. LangSmith tracing, feedback, and evals
