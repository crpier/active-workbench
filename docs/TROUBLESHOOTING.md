# Active Workbench - Troubleshooting

## Backend Not Reachable

Symptoms:
- OpenCode tool errors mention connection refused
- `active_workbench_*` tools fail immediately

Checks:
```bash
curl -s http://127.0.0.1:8000/health
```

If this fails, start backend:
```bash
just run
```

If using a different host/port, set:
- `ACTIVE_WORKBENCH_API_BASE_URL`

## OpenCode Not Seeing Custom Tools

Checks:
1. File exists: `.opencode/tools/active_workbench.ts`
2. Start OpenCode from project root:
```bash
opencode .
```
3. Use tool names prefixed by filename export, e.g.:
- `active_workbench_youtube_history_list_recent`

## OAuth Error 403: access_denied

If you see:
- "app has not completed verification"
- "only developer-approved testers"

Fix in Google Cloud Console:
1. Open correct project.
2. Go to `Google Auth Platform -> Audience`.
3. Add your login account under `Test users`.
4. Retry auth.

Then refresh local token:
```bash
rm -f .active-workbench/youtube-token.json
just youtube-auth-secret /path/to/client_secret.json
```

## Redirected to Google Auth Platform Instead of OAuth Consent Screen

Expected behavior. Google moved OAuth consent setup under `Google Auth Platform`:
- `Branding`
- `Audience`
- `Data Access`

## Using Wrong YouTube Account

Delete token and re-auth:
```bash
rm -f .active-workbench/youtube-token.json
just youtube-auth
```

## YouTube "Recent Watched" Shows Uploads Or Returns Unavailable

Current behavior:
- The backend now only accepts true watch history from YouTube's `watchHistory` playlist.
- It no longer falls back to `activities.list`, because that endpoint mostly returns channel activity (for many accounts: uploads), not watched videos.

If `youtube.history.list_recent` returns `youtube_unavailable`, this means YouTube did not expose watch history for your OAuth session/account through Data API.

Workarounds:
1. Use explicit video IDs/URLs with transcript and summary tools.
2. Stay in fixture mode for deterministic local development.

## Want to Keep Secret/Token Outside Project

Use env overrides:
- `ACTIVE_WORKBENCH_YOUTUBE_CLIENT_SECRET_PATH`
- `ACTIVE_WORKBENCH_YOUTUBE_TOKEN_PATH`

Example:
```bash
export ACTIVE_WORKBENCH_YOUTUBE_CLIENT_SECRET_PATH="$HOME/secrets/youtube-client-secret.json"
export ACTIVE_WORKBENCH_YOUTUBE_TOKEN_PATH="$HOME/secrets/youtube-token.json"
just youtube-auth
```

## Scheduler Side Effects During Debugging

Disable background scheduler while debugging:
```bash
ACTIVE_WORKBENCH_ENABLE_SCHEDULER=0 just run
```

## Reset Local Runtime State

Warning: removes local state DB and vault data.

```bash
rm -rf .active-workbench
```

Then re-run:
```bash
just setup
just gen-client
just run
```
