# Active Workbench - Quick Start

**Updated:** 2026-02-08

## What This Runs

This project is a local-first assistant backend + OpenCode custom tools setup:
- FastAPI backend (`backend/`) for tool contracts and persistence
- SQLite state database (`.active-workbench/state.db`)
- Markdown vault (`.active-workbench/vault/`)
- OpenCode custom tools (`.opencode/tools/active_workbench.ts`)

## Prerequisites

- `uv`
- `just`
- `node` + `npm`
- `opencode`

## First-Time Setup

```bash
cd /home/crpier/Projects/active-workbench
just setup
just gen-client
```

Optional verification:

```bash
just check
just ts-typecheck
```

## Run Backend + OpenCode

Terminal A:

```bash
cd /home/crpier/Projects/active-workbench
just run
```

Terminal B:

```bash
cd /home/crpier/Projects/active-workbench
opencode .
```

Project agent:
- This repo config sets `default_agent` to `workbench-assistant` in `opencode.json`.
- Agent prompt is stored at `.opencode/agents/workbench-assistant.md`.
- It is tuned to treat "watched/saw video" requests as liked-videos lookups.
- It is also tuned to proactively persist durable user context through `active_workbench_memory_create`.

## Use OpenCode Custom Tools

OpenCode auto-loads project tools from `.opencode/tools/`.

Examples:
- `active_workbench_youtube_likes_list_recent`
- `active_workbench_youtube_transcript_get`
- `active_workbench_recipe_extract_from_transcript`
- `active_workbench_vault_recipe_save`
- `active_workbench_memory_create`
- `active_workbench_reminder_schedule`

The tool returns are JSON envelopes from the backend (`ok`, `result`, `provenance`, `audit_event_id`, `undo_token`, `error`).

YouTube tool argument hints:
- `active_workbench_youtube_likes_list_recent`: pass `query`, `topic`, `limit`.
- `active_workbench_youtube_transcript_get`: pass `video_id` or `url`.

Query behavior:
- Likes lookup matches against title plus fetched video metadata (description, tags, channel), not title only.
- Query lookups use one extra YouTube Data API call for metadata enrichment.

Likes tool response fields:
- `liked_at`: when the video was liked (playlist item timestamp)
- `video_published_at`: original YouTube publish time
- `published_at`: kept for compatibility (same value as `liked_at`)
- `quota`: estimated daily YouTube Data API usage snapshot and warning flag

## YouTube Modes

### Fixture Mode (default)

No OAuth required. Used for local development and deterministic tests.

### OAuth Mode (real account)

Set mode when running backend:

```bash
ACTIVE_WORKBENCH_YOUTUBE_MODE=oauth just run
```

One-command auth bootstrap:

```bash
just youtube-auth-secret /path/to/google_client_secret.json
```

This will:
1. Copy the client secret to the configured location
2. Run OAuth browser flow
3. Save token to `.active-workbench/youtube-token.json`
4. Verify OAuth token setup

Note:
- `youtube.likes.list_recent` returns your recently liked videos (YouTube Data API `myRating=like`) and is used as the watched-video signal in agent flows.
- It does not use watch-history APIs.

If secret is already in place:

```bash
just youtube-auth
```

## Useful Environment Variables

- `ACTIVE_WORKBENCH_YOUTUBE_MODE=fixture|oauth`
- `ACTIVE_WORKBENCH_YOUTUBE_DAILY_QUOTA_LIMIT` (default `10000`)
- `ACTIVE_WORKBENCH_YOUTUBE_QUOTA_WARNING_PERCENT` (default `0.8`)
- `ACTIVE_WORKBENCH_DATA_DIR` (default `.active-workbench`)
- `ACTIVE_WORKBENCH_DEFAULT_TIMEZONE` (default `Europe/Bucharest`)
- `ACTIVE_WORKBENCH_ENABLE_SCHEDULER=1|0`
- `ACTIVE_WORKBENCH_YOUTUBE_CLIENT_SECRET_PATH`
- `ACTIVE_WORKBENCH_YOUTUBE_TOKEN_PATH`
- `ACTIVE_WORKBENCH_API_BASE_URL` (used by OpenCode custom tools; default `http://127.0.0.1:8000`)

## Inspect Data Quickly

Latest memories:

```bash
sqlite3 .active-workbench/state.db "
SELECT id, created_at, deleted_at, content_json
FROM memory_entries
ORDER BY created_at DESC
LIMIT 10;
"
```

Latest memory audit events:

```bash
sqlite3 .active-workbench/state.db "
SELECT id, tool_name, created_at
FROM audit_events
WHERE tool_name = 'memory.create'
ORDER BY created_at DESC
LIMIT 10;
"
```
