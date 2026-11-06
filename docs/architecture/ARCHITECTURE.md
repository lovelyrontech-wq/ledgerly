# Ledgerly — Architecture

Diagrams are written in Mermaid. They render on GitHub, GitLab, and in VS Code with a Mermaid preview extension.

## 1. System overview

```mermaid
flowchart LR
    user(["User<br/>(browser)"])

    subgraph web["apps/web — Next.js"]
        direction TB
        ui["UI<br/>folders, records,<br/>chat panel, preview dialog"]
        auth["Auth<br/>session login"]
        agent["Agent runtime<br/>tool-calling loop"]
        api["REST API<br/>/api/folders, /api/records,<br/>/api/batches, /api/audit"]
        perms["Permission checks<br/>owner / editor / viewer"]
        svc["Services<br/>records, batches,<br/>idempotency, audit"]
        obs["Observability<br/>tracing + feedback"]
    end

    subgraph mcp["packages/mcp-server"]
        tools["MCP tools<br/>list_records<br/>preview_bulk_update<br/>apply_bulk_update<br/>undo_batch<br/>search_help_docs"]
        client["REST client<br/>uses the user's token"]
    end

    subgraph kb["packages/knowledge"]
        docs[("Help docs<br/>Markdown")]
        index[("Vector index")]
    end

    subgraph local["Local machine"]
        ollama["Ollama<br/>chat: qwen2.5:7b-instruct<br/>embed: nomic-embed-text"]
    end

    db[("Database<br/>Postgres / SQLite<br/>users, folders, records,<br/>batches, batch_items, audit_log")]
    langsmith["LangSmith<br/>hosted or self-hosted"]

    user -->|"HTTPS"| ui
    ui --> auth
    ui -->|"chat message"| agent
    ui -->|"approve / cancel"| api
    agent -->|"chat + tool schemas"| ollama
    agent -->|"MCP tool calls<br/>as signed-in user"| tools
    tools --> client
    client -->|"HTTP + session token"| api
    tools -->|"search_help_docs"| index
    docs -->|"chunk + embed"| index
    index -.->|"embeddings"| ollama
    api --> perms --> svc --> db
    agent -.->|"traces"| obs
    obs -.->|"runs, spans, feedback"| langsmith

    classDef external fill:#fff4e5,stroke:#d97706,color:#000
    classDef store fill:#eef6ff,stroke:#2563eb,color:#000
    class ollama,langsmith external
    class db,docs,index store
```

**Trust boundaries**
- The agent has **no database access**. Its only path to data is the MCP tools, which call the REST API with the signed-in user's token. Permissions are checked in the API, the same as for the UI.
- **Approval comes from the UI, not the agent.** The user's click on **Approve** sends the preview ID to the API. The agent can propose a change, but the API rejects any apply without a matching approved preview.
- **Ollama** runs locally. **LangSmith** is the only component that sends data off the machine, and tracing can be turned off.

## 2. Bulk update: preview → approve → apply → undo

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant UI as Web UI
    participant AG as Agent
    participant LLM as Ollama
    participant MCP as MCP server
    participant API as REST API
    participant DB as Database

    U->>UI: "update the values in this folder by 10%"
    UI->>AG: chat message + folderId
    AG->>LLM: prompt + tool schemas
    LLM-->>AG: call preview_bulk_update(folderId, +10%)
    AG->>MCP: preview_bulk_update
    MCP->>API: POST /api/batches/preview (user token)
    API->>API: check user can edit folder
    API->>DB: read 40 records (id, valueCents, version)
    API->>DB: save batch (status: pending) + batch_items (old → new, version)
    API->>DB: audit_log: batch.preview
    API-->>MCP: previewId + 40 rows (old → new)
    MCP-->>AG: preview result
    AG-->>UI: preview table + Approve / Cancel
    UI-->>U: 40 records, old → new

    Note over U,UI: Nothing has been written yet

    U->>UI: click Approve
    UI->>API: POST /api/batches/{previewId}/apply<br/>Idempotency-Key: k1
    API->>API: check user, preview is pending and not expired
    loop each record in the preview
        API->>DB: UPDATE ... WHERE id = ? AND version = ?
        alt version matches
            DB-->>API: updated, version + 1
        else changed since preview
            DB-->>API: 0 rows
            API->>API: mark "changed since preview", skip
        end
    end
    API->>DB: batch status: applied, per-record results
    API->>DB: audit_log: batch.apply
    API-->>UI: results (applied 39, skipped 1)
    UI-->>U: per-record results + Undo button

    opt user clicks Apply again (retry / double click)
        UI->>API: same Idempotency-Key: k1
        API-->>UI: same stored result, no new writes
    end

    opt user asks "undo that"
        U->>AG: "undo the last change"
        AG->>MCP: undo_batch(batchId)
        MCP->>API: POST /api/batches/{batchId}/undo
        API->>DB: restore old values where version still matches
        API->>DB: audit_log: batch.undo
        API-->>AG: per-record undo results
        AG-->>U: "Restored 39 records"
    end
```

## 3. How-to question (RAG)

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant AG as Agent
    participant LLM as Ollama
    participant MCP as MCP server
    participant KB as Knowledge index

    U->>AG: "how do I share a folder?"
    AG->>LLM: prompt + tool schemas
    LLM-->>AG: call search_help_docs("share a folder")
    AG->>MCP: search_help_docs
    MCP->>LLM: embed query (nomic-embed-text)
    MCP->>KB: top-k similar chunks
    KB-->>MCP: chunks from sharing-and-permissions.md
    MCP-->>AG: chunks + source file names
    AG->>LLM: prompt + retrieved chunks
    LLM-->>AG: answer
    AG-->>U: answer with link to the help article
```

## 4. Data model

```mermaid
erDiagram
    USER ||--o{ FOLDER : owns
    USER ||--o{ FOLDER_PERMISSION : "is granted"
    FOLDER ||--o{ FOLDER_PERMISSION : "shared via"
    FOLDER ||--o{ RECORD : contains
    FOLDER ||--o{ BATCH : "changed by"
    BATCH ||--o{ BATCH_ITEM : includes
    RECORD ||--o{ BATCH_ITEM : "changed in"
    USER ||--o{ BATCH : creates
    USER ||--o{ AUDIT_LOG : "acts in"
    BATCH ||--o{ AUDIT_LOG : "logged in"

    USER {
        string id PK
        string email
        string name
        string passwordHash
    }
    FOLDER {
        string id PK
        string name
        string type "invoice | product"
        string ownerId FK
    }
    FOLDER_PERMISSION {
        string folderId FK
        string userId FK
        string role "editor | viewer"
    }
    RECORD {
        string id PK
        string folderId FK
        string name
        int valueCents
        string currency
        string status
        json fields
        int version
    }
    BATCH {
        string id PK
        string folderId FK
        string createdBy FK
        string status "pending | applied | undone | expired"
        string instruction
        string idempotencyKey
    }
    BATCH_ITEM {
        string batchId FK
        string recordId FK
        int before
        int after
        int expectedVersion
        string result
    }
    AUDIT_LOG {
        string id PK
        string userId FK
        string action
        string batchId FK
        json details
        datetime at
    }
```
