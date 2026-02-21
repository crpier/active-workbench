# Future Features

This is the staging space for features we plan to ship later.

## Current Incubator Items

- `Supadata search tool` (planned)
  - Code placeholder: `backend/app/services/incubator/supadata_search.py`
  - Status: scaffold only, no API calls yet.
- `OpenCode runtime artifacts integration` (planned)
  - Goal: evaluate using OpenCode-owned logs, transient state, and session files for debugging workflows and future backend-facing features.
  - Note: architecture boundary remains explicit: OpenCode owns runtime/session artifacts; Active Workbench may only consume them via an intentional integration contract.
  - Status: deferred by request; discovery/design later.

## Intent

- Keep production code clean while we shape new ideas.
- Define contracts early (request/response types), then wire tools when ready.
- Make design decisions explicit before exposing new capabilities.
