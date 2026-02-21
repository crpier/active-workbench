# AGENTS.md

This file is intentionally slim. Add rules here as recurring issues appear.

## Defaults
- Keep changes focused and minimal.
- Prefer small, testable diffs over broad refactors.
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
- Be explicit about architecture boundaries: OpenCode is the agent runtime that calls tools; the Active Workbench backend implements tools and backend logging/telemetry.

## Updates
- When a new issue repeats, add one concise rule here.
- For workbench-assistant YouTube "analyze all likes" tasks, avoid plan/subagent exploration loops and return one final answer after direct pagination.

## Debugging Files
- Runtime logs: `.active-workbench/logs/active-workbench.log` (or `$ACTIVE_WORKBENCH_LOG_DIR/active-workbench.log`)
- Telemetry events: `.active-workbench/logs/active-workbench-telemetry.log` (or `$ACTIVE_WORKBENCH_LOG_DIR/active-workbench-telemetry.log`)

## Docs Index
- `docs/QUICKSTART.md` - local setup and run commands.
- `docs/PRODUCTION.md` - production configuration and startup requirements.
- `docs/TROUBLESHOOTING.md` - operational debugging and common fixes.
- `docs/USER_GUIDE.md` - user-facing tool behavior and workflows.
- `docs/FUTURE_FEATURES.md` - incubator space for planned features.
