# Active Workbench

## Purpose

Build a personal assistant that manages notes, journals, recipes, reminders, and personal context through agent interaction only.

## MVP Summary

The MVP is chat-only and local-first:
- Chat is the only required interface.
- Backend and storage run on the development machine.
- YouTube integration uses OAuth with read-only access.
- Markdown is canonical content storage.
- SQLite stores operational state (memory, audit, jobs, metadata).
- Memory is auto-saved by default and always undoable.
- Tool API contracts are defined first, then implementation.

## Product Scope

In scope:
- Agent-first interaction through OpenCode.
- FastAPI backend exposing tool endpoints.
- TypeScript tool wrappers generated from the FastAPI OpenAPI schema.
- Local reminder scheduling and routine review generation.
- Provenance tracking and auditable writes.

Out of scope for MVP:
- VPS deployment.
- Voice/device channels.
- Manual CLI workflows as primary UX.
- Custom in-house LLM runtime.

## Primary User Stories (MVP)

### 1) Save Recipe From Recent YouTube Video

User story:
"Save the recipe from a recently watched YouTube cooking video."

Acceptance criteria:
1. Agent can list recent watched videos via OAuth-backed connector.
2. Agent fetches transcript with fallback behavior when possible.
3. Agent extracts recipe details (flexible schema in MVP).
4. Recipe is saved as markdown with source provenance.
5. A memory entry is created and returned with an undo option.
6. All writes are captured in audit logs.

### 2) Save Summary of Interesting YouTube Video

User story:
"I just watched an interesting YouTube video about microservices. Save a summary of the transcript with the most interesting ideas so that I can reference them later."

Acceptance criteria:
1. Agent identifies a recent relevant video.
2. Agent retrieves transcript and produces a concise summary.
3. Summary note is saved to markdown with source provenance.
4. Memory entry is created and undoable.

### 3) Save TV Show to Bucket List

User story:
"I just heard about a new cool TV show. Its name is X. Save it to my bucket list."

Acceptance criteria:
1. Agent captures item details from chat.
2. Item is saved in bucket list markdown.
3. A corresponding memory entry is recorded and undoable.

### 4) Perishable Item Reminder + Contextual Recipe Suggestions

User story:
"I just bought some leeks that will expire in three days. Remind me the day after tomorrow, in the morning, to cook them before they go bad."

Expected follow-up behavior:
If the user asks for a recipe in the next few days, suggestions should include options using leeks.

Acceptance criteria:
1. Agent stores item, expiry, and reminder schedule.
2. Reminder is scheduled for local morning in `Europe/Bucharest`.
3. Reminder event is auditable and user-visible.
4. Recipe queries consult expiring ingredients and prioritize relevant suggestions.

## Additional Planned Stories

1. Weekly learning digest  
"Summarize what I learned this week from saved YouTube notes, grouped by theme."
2. Action extraction from notes  
"From everything I saved this week, list actionable next steps and rank by impact."
3. Bucket list prioritization  
"Rank my bucket list by effort, cost, and how long items have been waiting."
4. Routine review workflow  
"Every Sunday morning, send me: expiring items, pending bucket-list tasks, and key notes to revisit."

Note:
For MVP, no fixed ranking algorithm will be implemented. Priority ordering is determined dynamically by the LLM at generation time.

## Architecture

### Component Overview

1. OpenCode agent runtime (chat orchestrator).
2. TypeScript tool layer (thin wrappers, generated API client usage).
3. FastAPI backend (business logic + validation + persistence orchestration).
4. Local storage:
   - Markdown files for canonical user content.
   - SQLite for memory, audit, jobs, provenance, and indices.

### Separation of Responsibilities

TypeScript tools:
- Validate incoming tool arguments.
- Call typed backend client generated from OpenAPI.
- Map backend errors to consistent tool errors.
- Do not contain file/SQLite business logic.

Python backend:
- Own all business logic and side effects.
- Handle persistence, audit, undo, and scheduling.
- Enforce schema validation and policy rules.

## Communication Model

Tool communication between OpenCode and backend uses HTTP/JSON over local network interfaces.

### Request envelope (conceptual)

```json
{
  "tool": "vault.recipe.save",
  "request_id": "uuid",
  "idempotency_key": "uuid",
  "payload": {},
  "context": {
    "timezone": "Europe/Bucharest",
    "session_id": "chat-session-id"
  }
}
```

### Response envelope (conceptual)

```json
{
  "ok": true,
  "request_id": "uuid",
  "result": {},
  "provenance": [],
  "audit_event_id": "evt_123",
  "undo_token": "undo_abc",
  "error": null
}
```

### API principles

- FastAPI is the contract authority via OpenAPI.
- TypeScript client is generated from backend OpenAPI schema.
- Write endpoints are idempotent when feasible.
- Uniform error shape includes retryability.

## Tool Surface (Initial)

YouTube:
- `youtube.history.list_recent`
- `youtube.transcript.get`

Vault/content:
- `vault.recipe.save`
- `vault.note.save`
- `vault.bucket_list.add`

Memory/audit:
- `memory.create`
- `memory.undo`

Planning/review/reminders:
- `reminder.schedule`
- `context.suggest_for_query`
- `digest.weekly_learning.generate`
- `review.routine.generate`

Extraction:
- `recipe.extract_from_transcript`
- `summary.extract_key_ideas`
- `actions.extract_from_notes`

## Data Model

### Markdown (canonical)

Planned folders:
- `vault/recipes/`
- `vault/notes/`
- `vault/bucket-list/`
- `vault/digests/`
- `vault/reviews/`

Each document should include frontmatter for:
- `id`
- `created_at`
- `updated_at`
- `source_refs`
- `tags` (optional)

### SQLite (operational state)

Core tables (proposed):
- `memory_entries`
- `memory_undo_log`
- `audit_events`
- `jobs`
- `job_runs`
- `sources`
- `entities`

Key behavior:
- Every write generates an audit event.
- Memory writes generate undo metadata.
- Jobs persist schedule and execution status.

## Scheduling and Time

- Default user timezone: `Europe/Bucharest`.
- "Morning" maps to a configurable local time (default `09:00`).
- Scheduler runs locally in backend process for MVP.
- Routine review cadence includes Sunday morning generation.

## Security and Policy Defaults

- Tool allowlist only.
- YouTube OAuth with minimum required read scopes.
- No direct DB/file access from agent runtime.
- Provenance attached to generated artifacts.
- Undo available for memory operations by default.

## Development Standards

The project is Python-first for backend implementation.

### Required tooling

- Command runner: `just`
- Python package/env management: `uv`
- Lint + formatting: `ruff`
- Type checking: `pyright` (strict)
- Testing: `pytest` with high coverage target

### Quality bar

- Strict linting and strict typing.
- Testable design with clear separation of service/repository layers.
- Dependency injection for external systems (YouTube, clock, filesystem, DB) where useful.
- Contract tests for API/tool interfaces.

## Repository Direction (Target)

```text
active-workbench/
  README.md
  justfile
  pyproject.toml
  uv.lock
  backend/
    app/
      main.py
      api/
      services/
      repositories/
      models/
      scheduler/
      security/
  tools-ts/
    src/
      tools/
      client/          # generated from OpenAPI
      adapters/
```

## Delivery Plan

1. Contract phase:
   - Define FastAPI schemas and tool endpoint contracts.
   - Generate TS client from OpenAPI and validate integration.
2. Core persistence phase:
   - Implement vault, memory, undo, and audit flows.
3. YouTube ingestion phase:
   - OAuth, history, transcript retrieval, provenance capture.
4. Workflow phase:
   - Recipe save, summary save, bucket-list save.
5. Reminder/context phase:
   - Perishable reminder scheduling + context-aware suggestions.
6. Review phase:
   - Weekly digest and routine review generation.

## Definition of Done (MVP)

MVP is done when:
1. All primary user stories complete end-to-end via chat.
2. All writes are auditable and memory writes are undoable.
3. Tool contracts are stable and consumed through generated TS client.
4. Local scheduler reliably executes reminders and routine reviews.
5. Codebase meets strict lint/type checks and high automated test coverage.
