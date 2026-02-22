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
- `Article knowledge pipeline + readable article workflow` (planned)
  - User story: user saves articles from phone/browser while browsing (often from social links or other articles), wants to stop tab hoarding, and later wants help choosing what to read, reading cleanly, and taking notes.
  - Core product direction: treat articles as a first-class content subsystem for knowledge capture/reading, while keeping a unified bucket as the entry/triage layer.
  - Architecture decision:
    - Keep `bucket_items` as the generic inbox/triage queue.
    - Add an article-specific entity/subsystem linked from bucket items for article lifecycle, extraction state, readable snapshots, and reading metadata.
    - Articles remain visible/manageable in bucket flows, but article storage and reader behavior are not modeled as generic bucket fields.
  - Capture inputs (Phase 1 target):
    - Android share intent endpoint
    - Browser extension share endpoint
    - Manual paste URL endpoint
  - Snapshot/storage decision (persist for reprocessing + archival):
    - Save original URL
    - Save original/raw HTML snapshot
    - Save cleaned readable version as Markdown (primary cleaned format)
    - Save metadata (title/canonical URL/author/publish date/site name when available)
    - Save ingestion timestamp
    - Save content hash (for dedupe/versioning support)
    - Treat saved articles as immutable snapshots (no silent auto-refresh of an existing snapshot)
  - Readable-content extraction pipeline (initial planned implementation):
    - Ingest URL into article pipeline
    - Perform initial cleanup/extraction with `trafilatura`
    - Use `Supadata scrape` + LLM polish as fallback when local extraction is low quality or fails
    - Store both source and cleaned outputs so extraction can be re-run/improved later
    - Keep LLM-polished output distinct from source extraction output if both are persisted (fidelity for notes/highlights)
  - Policy/guardrails (must define before shipping article ingestion):
    - Keep the workflow user-initiated (fetch/store URLs explicitly saved by the user), not broad discovery crawling
    - Respect site terms/robots guidance where applicable and document any exceptions/limitations of third-party fetch providers
    - Do not bypass paywalls, logins, or other access controls; only ingest content the user can lawfully access
    - Apply per-domain rate limits / backoff behavior (including honoring provider/site throttling signals where available)
    - Track provenance on stored snapshots (source URL, canonical URL, fetch timestamp, extraction method, and whether LLM polishing was used)
    - Define retention/deletion behavior for raw HTML, cleaned content, and metadata before mobile/browser capture is rolled out broadly
    - Default posture is personal-use knowledge capture/reading, not republishing or bulk redistribution of extracted content
  - Reader/UX direction:
    - Expose the cleaned/readable Markdown version in the app (not only the original URL)
    - Support re-opening the original URL as an option
    - Optimize for clean reading and archival stability rather than original page layout fidelity
    - Clean readable rendering is a priority for e-ink use (e.g. Onyx Boox)
    - EPUB generation/sync is a future enhancement; not required for initial implementation
  - Article lifecycle/state direction:
    - Article-specific lifecycle should support stages like capture/ingest -> extraction/cleanup -> readable -> read/notes
    - Track extraction status/failure reason to support manual retry
    - Track reading metadata needed for backlog management (at minimum saved date, read state, estimated reading time)
  - AI/knowledge-layer direction (planned progression):
    - Generate embeddings from cleaned Markdown
    - Support semantic search across saved articles
    - Support thematic grouping/topic clustering
    - Add article recommendation workflows (e.g. "I have 20 minutes, what should I read?")
    - Add first-class notes/highlights linked to articles for later cross-article reasoning
  - Implementation posture:
    - Prioritize low-maintenance personal-use reliability over universal scraping coverage
    - Focus on reducing cognitive load (capture + triage + recommendations + notes), with extraction treated as supporting infrastructure
  - Status: captured with architectural direction, initial extractor/fallback decisions, and required policy/guardrail reminders; implementation deferred.
- `Book review drafting assistant` (planned)
  - User story: after finishing a book, user wants guided help writing a personal review (for learning + reflection) and optionally preparing a publish-ready version.
  - Goal: offer a lightweight post-completion review flow (prompting, structure, draft iteration, optional publish-target formatting).
  - Integration direction: keep bucket completion intact and add a dedicated review workflow linked to completed book items.
  - Status: captured for future design; implementation deferred.
- `Project rename to match expanded scope` (deferred)
  - Goal: rename the project once scope and positioning are stable so
    the name reflects current capabilities.
  - Status: explicitly deferred; revisit during a future naming/branding
    pass.
- `Mobile QR enrollment for device keys` (deferred)
  - User story: user wants fast mobile pairing without copy/pasting long API keys.
  - Goal: add one-time, short-lived enrollment tokens (QR + manual fallback) so app can claim a per-device key securely.
  - Proposed flow: `create enrollment token -> scan QR in app -> claim device key once -> store in EncryptedSharedPreferences -> invalidate enrollment token`.
  - Status: captured for incubator; implementation deferred by request.
- `Cloud voice mode (STT/TTS)` (deferred)
  - User story: user wants higher-quality voice interaction than on-device Android speech tools.
  - Goal: add push-to-talk voice chat where audio is transcribed by cloud STT, sent programmatically into an assistant session, then played back via cloud TTS.
  - Scope notes: evaluate provider strategy (single vendor vs split STT/TTS), latency/cost targets, and whether voice shares session context with web/native text chat.
  - Status: captured for incubator; implementation deferred by request.
- `Security hardening + threat modeling pass` (deferred)
  - Context: current deployment can run Tailscale-only with reduced app-layer auth for a single-user bootstrap phase.
  - Goal: define the long-term security posture before broader use/exposure (network, app authn/authz, secrets handling, logging/telemetry exposure, backup access, device loss scenarios).
  - Deliverables: lightweight threat model, prioritized risks, and a staged hardening plan (quick wins vs later architecture changes).
  - Status: explicitly deferred for post-bootstrap hardening work.

## Intent

- Keep production code clean while we shape new ideas.
- Define contracts early (request/response types), then wire tools when ready.
- Make design decisions explicit before exposing new capabilities.
