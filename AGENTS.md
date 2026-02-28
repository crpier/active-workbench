# AGENTS.md

This file is intentionally slim. Add rules here as recurring issues appear.

## Defaults
- Treat the codebase as work-in-progress; broad changes are acceptable when they improve outcomes.
- Do not bias toward "safe/minimal" edits by default.
- Run targeted checks for touched code before finishing.
- Do not change unrelated files.

## Code
- Keep code style consistent.
- Code must be clear, concise, easy to read for humans.

## Communication
- State what changed and why, briefly.
- Flag tradeoffs or uncertainty explicitly.
- Ask the user before making design decisions or changing architectural direction.
- Default to behavior/outcome summaries; do not include file-by-file or code-location details unless the user asks.
- Keep architecture boundaries in mind internally; mention them in user-facing responses only when directly relevant or explicitly requested.

## Linting
- When `ruff` says says issues are fixable, use `just fix-linting`.
- Fix formatting by running `just format`.

## Updates
- When a new issue repeats, add one concise rule here.
- For workbench-assistant YouTube "analyze all likes" tasks, avoid plan/subagent exploration loops and return one final answer after direct pagination.
- For workbench-assistant bucket completion intents, execute `search -> complete` once and stop; do not chain extra tool calls or auto-memory writes.
- For live third-party API debugging (Supadata/YouTube), first correlate external dashboard timestamps to UTC and match them to local logs + telemetry by `scheduler_tick_id` before changing code.
- Treat third-party status codes as provider-specific; confirm payload `code/message/details` patterns in logs before inferring semantics from HTTP status alone.
- When credit usage looks abnormal, check for overlapping scheduler processes (different PIDs emitting scheduler ticks at the same time) before tuning retries.
- Prefer persisted throttles for expensive fallbacks (store last-attempt timestamps in `youtube_cache_state`) so limits survive restarts and apply across processes sharing the same DB.
- When adding fallback logic, log enough context to diagnose it later (`endpoint`, `mode`, `http_status`, provider details), and add targeted tests for both the fallback-success path and throttle/guard path.

## Debugging Files
- Runtime logs: `.active-workbench/logs/active-workbench.log` (or `$ACTIVE_WORKBENCH_LOG_DIR/active-workbench.log`)
- Telemetry events: `.active-workbench/logs/active-workbench-telemetry.log` (or `$ACTIVE_WORKBENCH_LOG_DIR/active-workbench-telemetry.log`)

## Docs Index
- `docs/QUICKSTART.md` - local setup and run commands.
- `docs/PRODUCTION.md` - production configuration and startup requirements.
- `docs/TROUBLESHOOTING.md` - operational debugging and common fixes.
- `docs/USER_GUIDE.md` - user-facing tool behavior and workflows.
- `docs/FUTURE_FEATURES.md` - incubator space for planned features.
