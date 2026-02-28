# Active Workbench

Active Workbench is a local-first assistant backend for three practical jobs:
1. working with your recently liked YouTube videos (lookup, search, transcript), and
2. managing a structured bucket list, and
3. storing and retrieving assistant memory (create/list/search/delete/undo).

It runs entirely on your machine with:
- FastAPI backend (`backend/`)
- SQLite runtime state (`.active-workbench/state.db`)
- OpenCode custom tools (`.opencode/tools/active_workbench.ts`)

## User Perspective: How It Works

1. You like videos in your own YouTube account.
2. You ask the assistant to find or search those liked videos.
3. The backend reads your liked-video signal from YouTube OAuth (`myRating=like`).
4. When you ask for transcript text, the backend retrieves captions via Supadata and caches results.
5. You add/update/search/recommend/complete bucket-list items.
6. All tool calls return a consistent JSON envelope (`ok`, `result`, `error`, `provenance`, `quota`).

## Currently Ready Tools

These tools are documented for active use:

YouTube:
- `youtube.likes.list_recent`
- `youtube.likes.search_recent_content`
- `youtube.transcript.get`

Bucket list:
- `bucket.item.add`
- `bucket.item.update`
- `bucket.item.complete`
- `bucket.item.search`
- `bucket.item.recommend`
- `bucket.health.report`

Bucket domains can include practical media/tasks plus research ideas (for example `domain=research`).

Memory:
- `memory.create`
- `memory.list`
- `memory.search`
- `memory.delete`
- `memory.undo`

## Documentation

- Quick setup and local run: `docs/QUICKSTART.md`
- Production mode (OAuth + fail-fast config): `docs/PRODUCTION.md`
- End-user behavior and workflows: `docs/USER_GUIDE.md`
- Troubleshooting: `docs/TROUBLESHOOTING.md`
- Incubator roadmap for planned tools: `docs/FUTURE_FEATURES.md`

## TMDb Attribution

This product uses the TMDB API but is not endorsed or certified by TMDB.

Movie and TV metadata enrichment for bucket-list items is provided by TMDb.
For terms and attribution details, see:
- `https://www.themoviedb.org/api-terms-of-use?language=en-US`

## Developer Notes

Core commands:

```bash
just setup
just gen-client
just run
just check
```

TypeScript client/tools:

```bash
just ts-typecheck
```
