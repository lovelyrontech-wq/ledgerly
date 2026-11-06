# Ledgerly — Use Case

## Overview

A mini SaaS app (folders of records, such as invoices or products) with an in-app agent that sets things up, answers how-to questions, and makes bulk changes.

## The demo moment

1. A user types: **"update the values in this folder by 10%"**.
2. The agent shows a **preview** of all 40 records (old → new).
3. The user **approves** it, and only then does it write the changes.
4. The agent can also **undo** the batch.

## Architecture

| Layer      | What to build |
|------------|---------------|
| App        | Next.js + TypeScript, simple login, folders and records in Postgres or SQLite |
| API        | REST endpoints for records, with per-user permissions |
| MCP server | Wraps the API as tools: `list_records`, `preview_bulk_update`, `apply_bulk_update`, `undo_batch`, `search_help_docs` |
| Agent      | Local LLM served by **Ollama**, with tool calling. It can only reach data through the MCP tools, as the signed-in user |
| Guardrails | Preview and approval tied to exact record IDs and values, idempotency keys, per-record results, and a full audit log |
| Knowledge  | A small RAG over help docs for the "how can I do this?" questions, with embeddings from Ollama |
| Observability | **LangSmith** tracing of every agent run: model calls, tool calls, RAG retrieval, latency, errors, and user feedback |

## Model (Ollama)

The agent and the RAG both run on a local Ollama server (default `http://localhost:11434`). Model calls stay on the machine. Traces sent to LangSmith are the one exception; see below.

| Purpose    | Default model        | Notes |
|------------|----------------------|-------|
| Agent chat | `qwen2.5:7b-instruct` | Must support tool calling. `llama3.1:8b` also works |
| Embeddings | `nomic-embed-text`   | Used to index and search the help docs |

Both are set by environment variables, so they can be swapped without code changes:

```
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=qwen2.5:7b-instruct
OLLAMA_EMBED_MODEL=nomic-embed-text
```

Smaller local models make more tool-calling mistakes than hosted ones, so the guardrails are enforced in the API, not trusted to the model. The agent cannot apply a change that was not previewed and approved by the user, whatever it outputs.

## Observability (LangSmith)

Every agent run is traced to LangSmith so we can see why the agent did what it did.

**One trace per chat turn**, tagged with user ID, folder ID, and batch ID (when there is one). Inside it:

| Span            | What it captures |
|-----------------|------------------|
| `agent_run`     | The whole turn: user message, final answer, total latency |
| `llm_call`      | Each Ollama chat call: model name, prompt, tool-call output, token counts, latency |
| `tool_call`     | Each MCP tool call: tool name, arguments, result summary, error if any |
| `rag_retrieval` | `search_help_docs`: query, top chunks returned, similarity scores |

**What it is used for:**
- **Debugging.** See the exact prompt and tool calls when the agent picks the wrong tool or wrong records.
- **Feedback.** Thumbs up/down in the chat panel is sent to LangSmith as feedback on that run.
- **Evals.** A small LangSmith dataset of test prompts (e.g. "increase this folder by 10%", "how do I export a folder?") is run against the agent to check tool choice and answers when the model or prompt changes.

**LangSmith does not replace the audit log.** The audit log in our database is the record of what changed and who approved it. LangSmith traces are for debugging and can be sampled or deleted.

**Data privacy.** LangSmith is a hosted service, so traces leave the machine. Record values and help-doc text will appear in prompts and tool results. Options:
- Turn tracing off (`LANGSMITH_TRACING=false`). The app works the same without it.
- Mask inputs and outputs (`LANGSMITH_HIDE_INPUTS=true`, `LANGSMITH_HIDE_OUTPUTS=true`) and keep only structure and timing.
- Use a self-hosted LangSmith instance by changing `LANGSMITH_ENDPOINT`.

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<your key>
LANGSMITH_PROJECT=ledgerly-dev
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

## Request flow

Full diagrams (system overview, preview → approve → apply → undo sequence, RAG flow, data model): [architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md).

```
User (browser)
   │  chat message
   ▼
Agent (Ollama model, server-side, runs as the signed-in user)
   │  tool calls only
   ▼
MCP server (list_records, preview_bulk_update, apply_bulk_update, undo_batch, search_help_docs)
   │  HTTP + user's session token
   ▼
REST API (per-user permission checks, idempotency, audit log)
   │
   ▼
Database (users, folders, records, batches, batch_items, audit_log)

Agent, LLM calls, tool calls, RAG  ──traces──▶  LangSmith
```

## Guardrail rules

- **Preview first.** `preview_bulk_update` computes old → new values and stores a pending batch. Nothing is written.
- **Approval is exact.** `apply_bulk_update` takes the preview ID. It writes only the record IDs and values in that preview. If any record changed since the preview, that record fails instead of being overwritten.
- **Idempotent.** Each apply carries an idempotency key. Repeating the call returns the first result and does not write twice.
- **Per-record results.** The apply response lists success or failure for each record.
- **Undo.** `undo_batch` restores the old values stored with the batch.
- **Audit log.** Every preview, apply, and undo is recorded with user, time, batch ID, and per-record before/after values.
- **No direct data access.** The agent never queries the database. Its only path is the MCP tools, scoped to the signed-in user.

## Sample data

Generated by `node scripts/generate-sample-data.mjs` into `packages/db/seed/`. The generator is seeded, so it always produces the same data.

All demo users share one password, set by `SEED_DEMO_PASSWORD` in `.env` (not committed).

| User | Login | Access |
|------|-------|--------|
| Alice | `alice@ledgerly.test` | Owns *Q3 2026 Invoices* and *Product Catalog* |
| Bob | `bob@ledgerly.test` | Owns *Bob's Consulting Invoices*; editor on Q3 Invoices |
| Carol | `carol@ledgerly.test` | Viewer on Q3 Invoices only |

| Folder | Records | Purpose |
|--------|---------|---------|
| Q3 2026 Invoices | 40 | The demo folder. Includes a zero value, a value that tests rounding (12.35 → 13.585), and a very large value |
| Product Catalog | 15 | Has one past batch (`bat_seed_001`, +5% on 3 products) so undo and history work on first run |
| Bob's Consulting Invoices | 8 (EUR) | Alice cannot see it; tests per-user permissions |

- Money is stored as integer cents (`valueCents`). Rounding is half-up to the nearest cent.
- Each record has a `version` that increases on every write. Apply uses it to skip records changed since the preview.
- Help docs for the RAG are in `packages/knowledge/help-docs/` (6 articles).
- Eval prompts for LangSmith are in `evals/datasets/agent-prompts.json` (9 cases, including a viewer trying to apply, cross-user access, and "just do it, skip the preview").

## Folder structure

```
Ledgerly/
├── docs/                      # Use case, architecture notes
│   └── architecture/
├── apps/
│   └── web/                   # Next.js app (UI + REST API + agent runtime)
│       ├── public/
│       ├── src/
│       │   ├── app/
│       │   │   ├── login/                       # Simple login page
│       │   │   ├── (dashboard)/folders/[folderId]/  # Folder + records view
│       │   │   └── api/                         # REST endpoints
│       │   │       ├── auth/
│       │   │       ├── folders/
│       │   │       ├── records/
│       │   │       ├── batches/                 # preview / apply / undo
│       │   │       ├── audit/
│       │   │       └── agent/                   # Chat endpoint for the agent
│       │   ├── components/
│       │   │   ├── records/                     # Record table, folder list
│       │   │   ├── agent/                       # Chat panel, preview/approve dialog
│       │   │   └── ui/
│       │   ├── lib/auth/                        # Session handling
│       │   └── server/
│       │       ├── services/                    # Record, batch, audit logic
│       │       ├── permissions/                 # Per-user access checks
│       │       ├── agent/                       # Ollama tool-calling loop + MCP client
│       │       └── observability/               # LangSmith tracing + feedback
│       └── tests/
├── packages/
│   ├── db/                    # Prisma schema, migrations, seed data
│   │   ├── prisma/migrations/
│   │   ├── src/
│   │   └── seed/
│   ├── mcp-server/            # MCP server wrapping the REST API
│   │   ├── src/tools/         # One file per tool
│   │   ├── src/client/        # Typed REST client (uses the user's token)
│   │   └── tests/
│   ├── shared/                # Zod schemas and shared types
│   │   └── src/{schemas,types}/
│   └── knowledge/             # RAG over help docs
│       ├── help-docs/         # Markdown help articles
│       └── src/               # Chunking, indexing, search
├── evals/                     # LangSmith eval datasets and runners
└── scripts/                   # Dev and seed helper scripts
```
