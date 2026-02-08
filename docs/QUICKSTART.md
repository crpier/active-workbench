# Active Workbench - Quick Start

**Updated:** 2026-02-08

## Use Model

Use Active Workbench by interacting with the assistant via chat or voice.

## Request Flow

1. User sends a prompt
2. Agent selects approved tools
3. Backend reads/writes vault and memory state
4. Agent responds with result and action visibility

## Storage Model

- Canonical content: markdown files
- Fast retrieval/state: SQLite index and memory tables

## Safety Defaults

- Tool allowlist only
- Integrations are read-only by default
- Memory auto-save with notification and undo

## First Milestone

Implement this workflow end-to-end:
- "Save the recipe from a recently watched YouTube cooking video"

Expected behavior:
1. Fetch recent watch history
2. Pull transcript
3. Extract structured recipe
4. Save recipe as markdown
5. Record provenance and memory entry
6. Offer undo for memory
