# Active Workbench - Production Mode

**Updated:** 2026-02-20

Production mode means:
- real YouTube OAuth
- startup fails fast if required secrets/config are missing

## 1. Prepare `.env`

From repo root:

```bash
cp .env.example .env
```

Set at least:

```env
ACTIVE_WORKBENCH_SUPADATA_API_KEY=YOUR_SUPADATA_API_KEY
ACTIVE_WORKBENCH_BUCKET_TMDB_API_KEY=YOUR_TMDB_API_KEY
ACTIVE_WORKBENCH_DATA_DIR=.active-workbench
```

Notes:
- `.env` is loaded automatically by backend settings.
- Shell env vars still work and override `.env`.
- `.env` is gitignored.
- Optional TMDb throttling knobs:
  - `ACTIVE_WORKBENCH_BUCKET_TMDB_DAILY_SOFT_LIMIT` (default `500`)
  - `ACTIVE_WORKBENCH_BUCKET_TMDB_MIN_INTERVAL_SECONDS` (default `1.1`)
- Optional transcript cadence tuning:
  - `ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_SCHEDULER_POLL_INTERVAL_SECONDS` (default `20`)
  - `ACTIVE_WORKBENCH_YOUTUBE_TRANSCRIPT_BACKGROUND_MIN_INTERVAL_SECONDS` (default `20`)

## 2. Bootstrap YouTube OAuth Files

Place your Google OAuth client secret and create token once:

```bash
just youtube-auth-secret /path/to/google_client_secret.json
```

After successful auth, these files must exist (default paths):
- `.active-workbench/youtube-client-secret.json`
- `.active-workbench/youtube-token.json`

You can override paths with:
- `ACTIVE_WORKBENCH_YOUTUBE_CLIENT_SECRET_PATH`
- `ACTIVE_WORKBENCH_YOUTUBE_TOKEN_PATH`

## 3. Run Backend (No Fixtures)

```bash
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

## 4. Fail-Fast Behavior

Startup fails immediately if any required production configuration is missing:
- `ACTIVE_WORKBENCH_SUPADATA_API_KEY`
- `ACTIVE_WORKBENCH_BUCKET_TMDB_API_KEY`
- OAuth client secret JSON file
- OAuth token JSON file

If `ACTIVE_WORKBENCH_YOUTUBE_MODE` is set, it must be `oauth`.
