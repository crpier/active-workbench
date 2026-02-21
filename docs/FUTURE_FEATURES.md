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
- `YouTube startup mode hardening` (deferred)
  - Goal: remove the setting that allows startup in non-OAuth YouTube modes and always start in OAuth mode.
  - Status: explicitly deferred for later implementation by user request.
- `Bucket context recovery for saved intents` (new)
  - User story: user saves "watch The Quick and the Dead" but later cannot remember why it was saved or which article/review referenced it.
  - Goal: let bucket entries preserve and recover source context ("why this was saved" + where it came from) when users revisit items.
  - Status: use case captured; design and implementation deferred.
- `Book review drafting assistant` (planned)
  - User story: after finishing a book, user wants guided help writing a personal review (for learning + reflection) and optionally preparing a publish-ready version.
  - Goal: offer a lightweight post-completion review flow (prompting, structure, draft iteration, optional publish-target formatting).
  - Integration direction: keep bucket completion intact and add a dedicated review workflow linked to completed book items.
  - Status: captured for future design; implementation deferred.

## Intent

- Keep production code clean while we shape new ideas.
- Define contracts early (request/response types), then wire tools when ready.
- Make design decisions explicit before exposing new capabilities.
