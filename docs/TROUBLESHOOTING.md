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
- `active_workbench_youtube_likes_list_recent`

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

## YouTube Likes Tool Returns Unavailable Or Empty

Current behavior:
- The backend reads `youtube.likes.list_recent` from YouTube Data API `videos.list(myRating=like)`.
- If your account has no liked videos (or likes are unavailable to the API session), the tool returns `youtube_unavailable`.

If `youtube.likes.list_recent` returns `youtube_unavailable`, verify:
1. You are authenticated with the expected YouTube account.
2. That account actually has liked videos.
3. You re-ran OAuth after switching accounts.

## YouTube Quota Warning In Tool Response

If `result.quota.warning=true` appears in YouTube tool responses, estimated daily Data API usage is above threshold.

Tune thresholds with env vars:
- `ACTIVE_WORKBENCH_YOUTUBE_DAILY_QUOTA_LIMIT`
- `ACTIVE_WORKBENCH_YOUTUBE_QUOTA_WARNING_PERCENT`

Workarounds:
1. Use explicit video IDs/URLs with transcript and summary tools.
2. Stay in fixture mode for deterministic local development.

## Transcript Tool Returns A Different Video Than Requested

Checks:
1. Call `active_workbench_youtube_transcript_get` with `video_id` or `url`.
2. Restart OpenCode after pulling latest changes so it reloads updated tool args.
3. Confirm backend is on latest code and restarted.

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
