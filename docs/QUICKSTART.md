# Active Workbench - Quick Start

**Updated:** 2026-02-20

## What This Runs

Local-first assistant backend + OpenCode tools:
- FastAPI backend (`backend/`)
- SQLite state database (`.active-workbench/state.db`)
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

## Run With YouTube OAuth

OAuth mode is the only supported runtime mode.

Run backend:

```bash
ACTIVE_WORKBENCH_YOUTUBE_MODE=oauth just run
```

Bootstrap OAuth once:

```bash
just youtube-auth-secret /path/to/google_client_secret.json
```

If secret is already in place:

```bash
just youtube-auth
```

## Production Mode

Use the production runbook:
- `docs/PRODUCTION.md`
- `docs/DEPLOY_TAILSCALE_VM.md` (recommended: VM + Tailscale + systemd)
- `docs/DEPLOY_NGINX_VM.md` (advanced: public VM + Nginx + TLS)

Short version:
1. `cp .env.example .env`
2. Set `ACTIVE_WORKBENCH_SUPADATA_API_KEY` and `ACTIVE_WORKBENCH_BUCKET_TMDB_API_KEY` (and optionally `ACTIVE_WORKBENCH_YOUTUBE_MODE=oauth`).
3. Ensure OAuth files exist (`youtube-client-secret.json`, `youtube-token.json`).
4. Run `uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`.

## Ready OpenCode Tools

OpenCode auto-loads tools from `.opencode/tools/`.

Only ready tools:
- `active_workbench_youtube_likes_list_recent`
- `active_workbench_youtube_likes_search_recent_content`
- `active_workbench_youtube_transcript_get`
- `active_workbench_bucket_item_add`
- `active_workbench_bucket_item_update`
- `active_workbench_bucket_item_complete`
- `active_workbench_bucket_item_search`
- `active_workbench_bucket_item_recommend`
- `active_workbench_bucket_health_report`

## Typical User Flows

1. Find recently liked videos:
```text
List my 5 most recent liked YouTube videos about cooking.
```

2. Search recent liked content:
```text
Search my recent liked videos for ideas about microservices trade-offs.
```

3. Get transcript for a selected video:
```text
Get transcript for https://www.youtube.com/watch?v=<video_id>
```

4. Manage bucket list items:
```text
Add "Watch Andor" to my bucket list.
Save "How to evaluate personal knowledge systems" as a research idea in my bucket list.
Recommend what I should watch next under 45 minutes.
Mark item <id> as completed.
```

## YouTube + Supadata Notes

- Liked videos come from YouTube Data API (`myRating=like`) via OAuth.
- Transcript retrieval uses Supadata.
- Likes and transcripts are cached in SQLite (`youtube_likes_cache`, `youtube_transcript_cache`).

## TMDb Attribution

This product uses the TMDB API but is not endorsed or certified by TMDB.

Movie and TV metadata enrichment for bucket-list items is sourced from TMDb.
Terms: `https://www.themoviedb.org/api-terms-of-use?language=en-US`

## Supadata Key Management (Recommended)

```bash
mkdir -p ~/.config/active-workbench
chmod 700 ~/.config/active-workbench
printf 'export ACTIVE_WORKBENCH_SUPADATA_API_KEY="YOUR_KEY"\n' > ~/.config/active-workbench/secrets.env
chmod 600 ~/.config/active-workbench/secrets.env
source ~/.config/active-workbench/secrets.env
```

## Useful Environment Variables

- `ACTIVE_WORKBENCH_YOUTUBE_MODE=oauth` (optional; any other value fails startup)
- `ACTIVE_WORKBENCH_SUPADATA_API_KEY` (required at startup for OAuth mode)
- `ACTIVE_WORKBENCH_BUCKET_TMDB_API_KEY` (required at startup for bucket enrichment)
- `ACTIVE_WORKBENCH_BUCKET_TMDB_DAILY_SOFT_LIMIT` (default `500` TMDb calls/day, UTC)
- `ACTIVE_WORKBENCH_BUCKET_TMDB_MIN_INTERVAL_SECONDS` (default `1.1`, burst guard between TMDb calls)
- `ACTIVE_WORKBENCH_BUCKET_BOOKWYRM_BASE_URL` (default `https://bookwyrm.social`)
- `ACTIVE_WORKBENCH_BUCKET_BOOKWYRM_USER_AGENT` (default includes app + repo URL; set your own contact)
- `ACTIVE_WORKBENCH_BUCKET_BOOKWYRM_DAILY_SOFT_LIMIT` (default `500` BookWyrm calls/day, UTC)
- `ACTIVE_WORKBENCH_BUCKET_BOOKWYRM_MIN_INTERVAL_SECONDS` (default `1.1`, burst guard between BookWyrm calls)
- `ACTIVE_WORKBENCH_BUCKET_MUSICBRAINZ_BASE_URL` (default `https://musicbrainz.org`)
- `ACTIVE_WORKBENCH_BUCKET_MUSICBRAINZ_USER_AGENT` (default includes app + repo URL; set your own contact)
- `ACTIVE_WORKBENCH_BUCKET_MUSICBRAINZ_DAILY_SOFT_LIMIT` (default `500` MusicBrainz calls/day, UTC)
- `ACTIVE_WORKBENCH_BUCKET_MUSICBRAINZ_MIN_INTERVAL_SECONDS` (default `1.1`, burst guard between MusicBrainz calls)
- `ACTIVE_WORKBENCH_SUPADATA_BASE_URL` (default `https://api.supadata.ai/v1`)
- `ACTIVE_WORKBENCH_SUPADATA_TRANSCRIPT_MODE` (default `native`)
- `ACTIVE_WORKBENCH_DATA_DIR` (default `.active-workbench`)
- `ACTIVE_WORKBENCH_YOUTUBE_CLIENT_SECRET_PATH`
- `ACTIVE_WORKBENCH_YOUTUBE_TOKEN_PATH`
- `ACTIVE_WORKBENCH_SCHEDULER_POLL_INTERVAL_SECONDS` (default `60`, jobs + likes sync)
- `ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_SCHEDULER_POLL_INTERVAL_SECONDS` (default `20`, transcript sync loop)
- `ACTIVE_WORKBENCH_YOUTUBE_BACKGROUND_MIN_INTERVAL_SECONDS` (default `180`)
- `ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_BACKGROUND_MIN_INTERVAL_SECONDS` (default `20`)
- `ACTIVE_WORKBENCH_API_BASE_URL` (default `http://127.0.0.1:8000`)
- `ACTIVE_WORKBENCH_LOG_DIR` (default `.active-workbench/logs`)
- `ACTIVE_WORKBENCH_TELEMETRY_ENABLED` (default `true`; set `false` to disable telemetry events)
- `ACTIVE_WORKBENCH_TELEMETRY_SINK` (default `log`; set `none` to suppress sink output)

Log files written under `ACTIVE_WORKBENCH_LOG_DIR`:
- app/runtime logs: `active-workbench.log`
- telemetry events: `active-workbench-telemetry.log`

## Quick Runtime Checks

Health endpoint:

```bash
curl -s http://127.0.0.1:8000/health
```

Latest cached liked videos:

```bash
sqlite3 .active-workbench/state.db "
SELECT video_id, title, liked_at
FROM youtube_likes_cache
ORDER BY liked_at DESC
LIMIT 10;
"
```

Latest bucket items:

```bash
sqlite3 .active-workbench/state.db "
SELECT id, title, domain, status, added_at
FROM bucket_items
ORDER BY added_at DESC
LIMIT 10;
"
```
