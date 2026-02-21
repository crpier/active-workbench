# Active Workbench - User Guide

## What You Can Do Today

Active Workbench currently supports three user-facing capabilities:
1. Work with your recently liked YouTube videos.
2. Maintain a structured bucket list.
3. Save and retrieve memory entries for continuity.

## How The System Behaves (User View)

When you interact through OpenCode:

1. You ask in natural language.
2. The assistant chooses one of the ready tools.
3. The backend validates input and runs the operation.
4. Results are returned in a consistent envelope:
   - `ok`
   - `result`
   - `error` (if any)
   - `provenance`
   - `quota` (for YouTube-related tools)

Caching behavior:
- Liked-video results are cached.
- Transcript results are cached.
- Cache metadata is included in responses (`result.cache`).

## YouTube Workflow

### 1) Find recent liked videos

Use:
- `youtube.likes.list_recent`

What it does:
- Reads liked videos from your YouTube account (`myRating=like`) in OAuth mode.
- Supports topic/query filtering.
- Returns metadata such as title, channel, `liked_at`, and `video_published_at`.

### 2) Search recent liked content

Use:
- `youtube.likes.search_recent_content`

What it does:
- Searches recent liked videos by title, description, and cached transcript text.
- Returns ranked matches with snippets.

### 3) Fetch transcript

Use:
- `youtube.transcript.get`

What it does:
- Retrieves transcript for a YouTube video ID or URL.
- In OAuth mode, transcript retrieval is performed through Supadata.
- Returns transcript text and segments when available.

## Bucket List Workflow

### Structured bucket list

Use:
- `bucket.item.add`
- `bucket.item.update`
- `bucket.item.complete`
- `bucket.item.search`
- `bucket.item.recommend`
- `bucket.health.report`

What it does:
- Keeps items as structured records in SQLite.
- Supports filtering, recommendations, and health diagnostics.
- Duplicate add requests for an already-active item return `status=already_exists` (no write).
- Requires explicit domain on add (for example movie, tv, book, music, game, place, travel).
- For `movie`/`tv`, add requests run TMDb resolution before write.
  - If match is uncertain, `bucket.item.add` returns `status=needs_clarification` with candidates.
  - Confirm by retrying `bucket.item.add` with `tmdb_id` (chat follow-up, no question tool needed).
  - Optional escape hatch: `allow_unresolved=true` writes without confirmation.
  - Low-signal obscure matches are skipped by default unless you give explicit disambiguation (for example `year` or `tmdb_id`).
- For `book`, add requests run BookWyrm resolution before write.
  - If match is uncertain, `bucket.item.add` returns `status=needs_clarification` with candidates.
  - Confirm by choosing an option (for example by author/year); assistant then retries with the mapped `bookwyrm_key`.
  - BookWyrm requests include an explicit User-Agent and follow local soft-limit/burst guardrails.
- For `music` (albums), add requests run MusicBrainz resolution before write.
  - Album-only matching is enforced (`primarytype:album`), so songs/singles are excluded.
  - Artist hints are used when available (for example payload `artist` or notes like "album by Scardust") to reduce noise.
  - If match is uncertain, `bucket.item.add` returns `status=needs_clarification` with candidates.
  - Confirm by choosing an option (for example by artist/year); assistant then retries with the mapped `musicbrainz_release_group_id`.
  - MusicBrainz requests include an explicit User-Agent and follow local soft-limit/burst guardrails.
- For `article`, add requests are URL-first.
  - Provide `url` (or `external_url`) and `domain=article`.
  - Backend fetches page metadata (title/author/site/published date/description), normalizes canonical URL, and deduplicates by canonical article URL.
  - If URL is missing, `bucket.item.add` returns `status=needs_clarification` requesting the article link.
- Background annotation runs periodically (scheduler loop) to enrich low-detail items.
- Search results include unannotated items and expose their annotation status.
- Recommendations exclude unannotated items.

## Memory Workflow

Use:
- `memory.create`
- `memory.list`
- `memory.search`
- `memory.delete`
- `memory.undo`

What it does:
- Stores short durable memory entries with optional tags and source refs.
- Returns an `undo_token` on create so writes can be reverted quickly.
- Supports listing recent active memory and searching by query/tags.
- Supports deleting memory by `memory_id`.

## OpenCode Tool Names

In OpenCode, these are exposed as:

- `active_workbench_youtube_likes_list_recent`
- `active_workbench_youtube_likes_search_recent_content`
- `active_workbench_youtube_transcript_get`
- `active_workbench_bucket_item_add`
- `active_workbench_bucket_item_update`
- `active_workbench_bucket_item_complete`
- `active_workbench_bucket_item_search`
- `active_workbench_bucket_item_recommend`
- `active_workbench_bucket_health_report`
- `active_workbench_memory_create`
- `active_workbench_memory_list`
- `active_workbench_memory_search`
- `active_workbench_memory_delete`
- `active_workbench_memory_undo`

## Practical Prompt Examples

- "Show my last 5 liked videos about Rust performance."
- "Search recent liked videos for material on microservices trade-offs."
- "Get transcript for https://www.youtube.com/watch?v=<video_id>."
- "Add 'Watch Andor' to my bucket list."
- "Recommend one bucket item I can do in under 45 minutes."
- "Mark item <id> as completed."

## Required User Setup For YouTube Transcripts

For OAuth mode with transcripts:
1. Complete YouTube OAuth setup (`just youtube-auth` or `just youtube-auth-secret ...`).
2. Set Supadata API key (`ACTIVE_WORKBENCH_SUPADATA_API_KEY`).

## TMDb Attribution

This product uses the TMDB API but is not endorsed or certified by TMDB.

Bucket list movie/TV enrichment uses TMDb data.
Terms: `https://www.themoviedb.org/api-terms-of-use?language=en-US`

See:
- `docs/QUICKSTART.md`
- `docs/TROUBLESHOOTING.md`
