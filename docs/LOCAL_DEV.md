# Run Ledgerly locally

Ledgerly has four parts. Run each one in its own terminal.

| Part | Address | What it does |
|---|---|---|
| Ollama | http://localhost:11434 | The local AI model |
| MCP tool server | http://localhost:8001/mcp | The tools the agent uses (records, bulk changes, help search) |
| API (FastAPI) | http://localhost:8000 | REST API and agent chat. Docs: http://localhost:8000/docs |
| Web app (Next.js) | http://localhost:3000 | The UI |

## First time only (or after pulling new code)

```powershell
# Backend
cd C:\upword\Ledgerly\backend
copy .env.example .env          # first time only, then fill in AUTH_SECRET and SEED_DEMO_PASSWORD
uv sync --extra langgraph       # Python packages, including the LangGraph engine
uv run alembic upgrade head     # create/update the database
uv run ledgerly-seed            # load demo data (only on an empty database)

# Models (once)
ollama pull qwen2.5:7b-instruct
ollama pull nomic-embed-text

# Frontend
cd C:\upword\Ledgerly\apps\web
npm install
```

To create an `AUTH_SECRET`:

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Start the app

**Terminal 1: Ollama** (skip it if Ollama is already running in the background)

```powershell
ollama serve
```

**Terminal 2: MCP tool server**

```powershell
cd C:\upword\Ledgerly\backend
uv run python -m ledgerly.mcp_server
```

**Terminal 3: API**

```powershell
cd C:\upword\Ledgerly\backend
uv run uvicorn ledgerly.api.app:create_app --factory --reload --port 8000
```

**Terminal 4: Web app**

```powershell
cd C:\upword\Ledgerly\apps\web
npm run dev
```

Open http://localhost:3000 and sign in:

- Email: `alice@ledgerly.test`
- Password: the `SEED_DEMO_PASSWORD` value in `backend/.env`

To stop a server, press `Ctrl+C` in its terminal.

## Optional: LangSmith tracing

Every agent message becomes one trace, tagged `engine:plain` or `engine:langgraph`, with its speed numbers.
Set these in `backend/.env`, then restart the API:

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=ledgerly-dev
```

If the key is empty, the API logs a warning and runs without tracing.

## Tests

```powershell
# Backend (no Ollama needed)
cd C:\upword\Ledgerly\backend
uv run pytest -m "not ollama"

# Frontend
cd C:\upword\Ledgerly\apps\web
npm run typecheck
npm run lint
npm test                        # unit tests (Vitest)
npx playwright install chromium # first time only
npm run test:e2e                # needs the API and MCP server running; set E2E_PASSWORD first
```

## Problems

| What you see | Fix |
|---|---|
| Chat says the tool server (MCP) is not reachable | Start terminal 2 |
| Chat says Ollama is not reachable | Start Ollama (`ollama serve`) |
| API does not start: "LangGraph is not installed" | Run `uv sync --extra langgraph`. Plain `uv sync` removes it. |
| API does not start: "AUTH_SECRET must be set" | Set `AUTH_SECRET` in `backend/.env` (at least 32 characters) |
| Chat answers take 30–50 seconds | Normal on a CPU-only PC with the 7B model. Close other programs to free RAM (the model needs about 5 GB). |
| "address already in use" | That server is already running. Close the old terminal or use another port. |
