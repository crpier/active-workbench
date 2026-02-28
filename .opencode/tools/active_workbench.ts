import { tool } from "@opencode-ai/plugin";

import { ToolClient, createToolRequest } from "../../tools-ts/src/tools/index";
import type { ToolRequest } from "../../tools-ts/src/client/models/ToolRequest";

const DEFAULT_BASE_URL = "http://127.0.0.1:8000";

const TOOL_NAMES = {
  youtube_likes_list_recent: "youtube.likes.list_recent",
  youtube_likes_search_recent_content: "youtube.likes.search_recent_content",
  youtube_watch_later_list: "youtube.watch_later.list",
  youtube_watch_later_search_content: "youtube.watch_later.search_content",
  youtube_watch_later_recommend: "youtube.watch_later.recommend",
  youtube_transcript_get: "youtube.transcript.get",
  bucket_item_add: "bucket.item.add",
  bucket_item_update: "bucket.item.update",
  bucket_item_complete: "bucket.item.complete",
  bucket_item_search: "bucket.item.search",
  bucket_item_recommend: "bucket.item.recommend",
  bucket_health_report: "bucket.health.report",
  memory_create: "memory.create",
  memory_list: "memory.list",
  memory_search: "memory.search",
  memory_delete: "memory.delete",
  memory_undo: "memory.undo",
} as const;

type BackendToolName = (typeof TOOL_NAMES)[keyof typeof TOOL_NAMES];

type ToolArgs = {
  payload?: Record<string, unknown>;
  timezone?: string;
  session_id?: string;
  idempotency_key?: string;
  [key: string]: unknown;
};

function getClient(): ToolClient {
  return new ToolClient({
    baseUrl: process.env.ACTIVE_WORKBENCH_API_BASE_URL ?? DEFAULT_BASE_URL,
    token: process.env.ACTIVE_WORKBENCH_API_TOKEN,
  });
}

function backendTool(
  toolName: BackendToolName,
  description: string,
  options?: {
    extraArgs?: Record<string, unknown>;
    payloadFields?: string[];
    requireAnyField?: string[];
  },
) {
  const extraArgs = options?.extraArgs ?? {};
  const payloadFields = options?.payloadFields ?? [];
  const requireAnyField = options?.requireAnyField ?? [];

  return tool({
    description,
    args: {
      payload: tool.schema
        .record(tool.schema.string(), tool.schema.any())
        .default({})
        .describe("JSON payload for the backend tool"),
      timezone: tool.schema
        .string()
        .default("Europe/Bucharest")
        .describe("Timezone for scheduling/context"),
      session_id: tool.schema
        .string()
        .optional()
        .describe("Optional session identifier override"),
      idempotency_key: tool.schema
        .string()
        .uuid()
        .optional()
        .describe("Optional idempotency key for write tools"),
      ...extraArgs,
    },
    async execute(args, context) {
      const argsValue = args as ToolArgs;
      const payload: Record<string, unknown> = {
        ...(argsValue.payload ?? {}),
      };

      for (const field of payloadFields) {
        const value = argsValue[field];
        if (value !== undefined && value !== null && value !== "") {
          payload[field] = value;
        }
      }

      if (
        requireAnyField.length > 0 &&
        !requireAnyField.some((field) => {
          const direct = argsValue[field];
          if (direct !== undefined && direct !== null && direct !== "") {
            return true;
          }
          const inPayload = payload[field];
          return inPayload !== undefined && inPayload !== null && inPayload !== "";
        })
      ) {
        throw new Error(`One of the following fields is required: ${requireAnyField.join(", ")}`);
      }

      const request = createToolRequest({
        tool: toolName,
        payload,
        sessionId: argsValue.session_id ?? context.sessionID,
        timezone: argsValue.timezone,
      });

      if (argsValue.idempotency_key) {
        request.idempotency_key = argsValue.idempotency_key;
      }

      const response = await getClient().callTool(request as ToolRequest);
      return JSON.stringify(response, null, 2);
    },
  });
}

export const youtube_likes_list_recent = backendTool(
  TOOL_NAMES.youtube_likes_list_recent,
  "List recently liked YouTube videos; use this for user requests like watched/saw/seen videos and filter by query/topic. Supports cursor pagination for full-history scans.",
  {
    extraArgs: {
      limit: tool.schema.any().optional().describe("Maximum number of liked videos to fetch for this page."),
      cursor: tool.schema
        .number()
        .int()
        .optional()
        .describe("Optional page cursor from result.next_cursor; start at 0 or omit."),
      compact: tool.schema
        .boolean()
        .optional()
        .describe("Return compact video payload (recommended for full-history analysis)."),
      query: tool.schema
        .string()
        .optional()
        .describe("Filter liked videos by title/content topic."),
      topic: tool.schema
        .string()
        .optional()
        .describe("Alias for query."),
    },
    payloadFields: ["limit", "cursor", "compact", "query", "topic"],
  },
);

export const youtube_transcript_get = backendTool(
  TOOL_NAMES.youtube_transcript_get,
  "Fetch transcript for a specific YouTube video. Provide video_id or url.",
  {
    extraArgs: {
      video_id: tool.schema
        .string()
        .optional()
        .describe("YouTube video ID, for example 4qfsmE11Ejo."),
      url: tool.schema
        .string()
        .optional()
        .describe("YouTube URL; backend extracts the video ID."),
    },
    payloadFields: ["video_id", "url"],
  },
);

export const youtube_likes_search_recent_content = backendTool(
  TOOL_NAMES.youtube_likes_search_recent_content,
  "Search recent liked YouTube content by title/description/transcript matches.",
  {
    extraArgs: {
      query: tool.schema.string().optional().describe("Search query text."),
      window_days: tool.schema
        .number()
        .int()
        .optional()
        .describe("Optional lookback window in days. Omit to search across all cached likes."),
      limit: tool.schema.number().int().optional().describe("Maximum number of matches."),
    },
    payloadFields: ["query", "window_days", "limit"],
  },
);

export const youtube_watch_later_list = backendTool(
  TOOL_NAMES.youtube_watch_later_list,
  "List cached watch later videos from pushed snapshots.",
  {
    extraArgs: {
      limit: tool.schema.any().optional().describe("Maximum number of videos to fetch."),
      cursor: tool.schema
        .number()
        .int()
        .optional()
        .describe("Optional page cursor from result.next_cursor."),
      compact: tool.schema.boolean().optional().describe("Return compact payload."),
      query: tool.schema.string().optional().describe("Optional filter query."),
      topic: tool.schema.string().optional().describe("Alias for query."),
      include_removed: tool.schema
        .boolean()
        .optional()
        .describe("Include removed watch-later rows."),
    },
    payloadFields: ["limit", "cursor", "compact", "query", "topic", "include_removed"],
  },
);

export const youtube_watch_later_search_content = backendTool(
  TOOL_NAMES.youtube_watch_later_search_content,
  "Search watch later content by title/description/transcript.",
  {
    extraArgs: {
      query: tool.schema.string().optional().describe("Search query text."),
      window_days: tool.schema
        .number()
        .int()
        .optional()
        .describe("Optional lookback window in days."),
      limit: tool.schema.number().int().optional().describe("Maximum number of matches."),
      include_removed: tool.schema
        .boolean()
        .optional()
        .describe("Include removed watch-later rows."),
    },
    payloadFields: ["query", "window_days", "limit", "include_removed"],
  },
);

export const youtube_watch_later_recommend = backendTool(
  TOOL_NAMES.youtube_watch_later_recommend,
  "Recommend one watch later video by topic and optional duration target.",
  {
    extraArgs: {
      query: tool.schema.string().optional().describe("Topic or query hint."),
      topic: tool.schema.string().optional().describe("Alias for query."),
      target_minutes: tool.schema
        .number()
        .int()
        .optional()
        .describe("Preferred video length in minutes."),
      duration_tolerance_minutes: tool.schema
        .number()
        .int()
        .optional()
        .describe("Allowed duration gap in minutes."),
      include_removed: tool.schema
        .boolean()
        .optional()
        .describe("Include removed watch-later rows."),
    },
    payloadFields: [
      "query",
      "topic",
      "target_minutes",
      "duration_tolerance_minutes",
      "include_removed",
    ],
  },
);

export const bucket_item_add = backendTool(
  TOOL_NAMES.bucket_item_add,
  "Add or merge a structured bucket item. Domain is required. For movie/tv/book/music, backend may return status=needs_clarification with provider candidates; ask the user to choose by option number or creator clues in normal chat (not by raw provider id), then call again with the matching provider id field. Do not call a question tool.",
  {
    extraArgs: {
      title: tool.schema.string().optional().describe("Item title."),
      domain: tool.schema.string().describe("Required domain (for example movie, tv, book, music, game, place, travel)."),
      url: tool.schema.string().optional().describe("Optional URL."),
      artist: tool.schema
        .string()
        .optional()
        .describe("Optional artist hint for music album matching."),
      notes: tool.schema.string().optional().describe("Optional notes/description."),
      year: tool.schema.number().int().optional().describe("Optional release year hint (movie/tv)."),
      tmdb_id: tool.schema
        .number()
        .int()
        .optional()
        .describe("TMDb id to confirm the exact movie/tv match."),
      bookwyrm_key: tool.schema
        .string()
        .optional()
        .describe("BookWyrm key URL to confirm the exact book match."),
      musicbrainz_release_group_id: tool.schema
        .string()
        .optional()
        .describe("MusicBrainz release-group id to confirm the exact album match."),
      allow_unresolved: tool.schema
        .boolean()
        .optional()
        .describe("Allow write even when provider match is ambiguous/no-match/rate-limited."),
      auto_enrich: tool.schema
        .boolean()
        .optional()
        .describe("When true, perform provider enrichment for non-media domains."),
    },
    payloadFields: [
      "title",
      "domain",
      "url",
      "artist",
      "notes",
      "year",
      "tmdb_id",
      "bookwyrm_key",
      "musicbrainz_release_group_id",
      "allow_unresolved",
      "auto_enrich",
    ],
  },
);

export const bucket_item_update = backendTool(
  TOOL_NAMES.bucket_item_update,
  "Update a structured bucket item. Include item_id plus changed fields. Do not use this to mark completion; use bucket_item_complete.",
  {
    extraArgs: {
      item_id: tool.schema.string().optional().describe("Bucket item id to update."),
      id: tool.schema.string().optional().describe("Alias for item_id."),
      title: tool.schema.string().optional().describe("Updated title."),
      domain: tool.schema.string().optional().describe("Updated domain."),
      notes: tool.schema.string().optional().describe("Updated notes."),
      year: tool.schema.number().int().optional().describe("Updated year."),
      duration_minutes: tool.schema.number().int().optional().describe("Updated duration in minutes."),
      rating: tool.schema.number().optional().describe("Updated rating."),
      popularity: tool.schema.number().optional().describe("Updated popularity."),
      genres: tool.schema
        .array(tool.schema.string())
        .optional()
        .describe("Updated genres list."),
      tags: tool.schema.array(tool.schema.string()).optional().describe("Updated tags list."),
      providers: tool.schema
        .array(tool.schema.string())
        .optional()
        .describe("Updated provider/platform list."),
      external_url: tool.schema.string().optional().describe("Updated external URL."),
      confidence: tool.schema.number().optional().describe("Updated confidence score."),
    },
    payloadFields: [
      "item_id",
      "id",
      "title",
      "domain",
      "notes",
      "year",
      "duration_minutes",
      "rating",
      "popularity",
      "genres",
      "tags",
      "providers",
      "external_url",
      "confidence",
    ],
  },
);

export const bucket_item_complete = backendTool(
  TOOL_NAMES.bucket_item_complete,
  "Mark a structured bucket item as completed (kept in storage but hidden from active views). Requires item_id/id/bucket_item_id and should be called once per completion action.",
  {
    extraArgs: {
      item_id: tool.schema.string().optional().describe("Bucket item id to complete."),
      id: tool.schema.string().optional().describe("Alias for item_id."),
      bucket_item_id: tool.schema.string().optional().describe("Alias for item_id."),
    },
    payloadFields: ["item_id", "id", "bucket_item_id"],
    requireAnyField: ["item_id", "id", "bucket_item_id"],
  },
);

export const bucket_item_search = backendTool(
  TOOL_NAMES.bucket_item_search,
  "Search structured bucket items by query/domain/genre/duration/rating. Includes annotation status so unannotated items can be identified.",
  {
    extraArgs: {
      query: tool.schema.string().optional().describe("Free-text query against title/notes."),
      domain: tool.schema.string().optional().describe("Domain filter (movie, tv, book, etc.)."),
      include_completed: tool.schema
        .boolean()
        .optional()
        .describe("Include completed items in results."),
      limit: tool.schema.number().int().optional().describe("Maximum number of returned items."),
    },
    payloadFields: ["query", "domain", "include_completed", "limit"],
  },
);

export const bucket_item_recommend = backendTool(
  TOOL_NAMES.bucket_item_recommend,
  "Recommend best-fit bucket items from constraints such as genre and duration. Unannotated items are excluded.",
);

export const bucket_health_report = backendTool(
  TOOL_NAMES.bucket_health_report,
  "Generate bucket health diagnostics including stale items, metadata gaps, and quick wins.",
);

export const memory_create = backendTool(
  TOOL_NAMES.memory_create,
  "Create a persistent memory entry with undo support. Prefer concise factual memory text.",
  {
    extraArgs: {
      text: tool.schema.string().optional().describe("Memory text to store."),
      fact: tool.schema.string().optional().describe("Alias for text."),
      tags: tool.schema
        .array(tool.schema.string())
        .optional()
        .describe("Optional memory tags for retrieval."),
      type: tool.schema
        .string()
        .optional()
        .describe("Optional memory type (preference, reminder, context, note)."),
    },
    payloadFields: ["text", "fact", "tags", "type"],
    requireAnyField: ["text", "fact"],
  },
);

export const memory_list = backendTool(
  TOOL_NAMES.memory_list,
  "List recent active memories.",
  {
    extraArgs: {
      limit: tool.schema.number().int().optional().describe("Maximum memories to return."),
    },
    payloadFields: ["limit"],
  },
);

export const memory_search = backendTool(
  TOOL_NAMES.memory_search,
  "Search active memories by text and tags.",
  {
    extraArgs: {
      query: tool.schema.string().optional().describe("Text query for memory retrieval."),
      tags: tool.schema
        .array(tool.schema.string())
        .optional()
        .describe("Optional tag filters."),
      limit: tool.schema.number().int().optional().describe("Maximum search results."),
    },
    payloadFields: ["query", "tags", "limit"],
    requireAnyField: ["query", "tags"],
  },
);

export const memory_delete = backendTool(
  TOOL_NAMES.memory_delete,
  "Delete a memory by id.",
  {
    extraArgs: {
      memory_id: tool.schema.string().optional().describe("Memory id to delete."),
      id: tool.schema.string().optional().describe("Alias for memory_id."),
    },
    payloadFields: ["memory_id", "id"],
    requireAnyField: ["memory_id", "id"],
  },
);

export const memory_undo = backendTool(
  TOOL_NAMES.memory_undo,
  "Undo a memory entry using undo_token.",
);
