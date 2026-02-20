import { tool } from "@opencode-ai/plugin";

import { ToolClient, createToolRequest } from "../../tools-ts/src/tools/index";
import type { ToolRequest } from "../../tools-ts/src/client/models/ToolRequest";

const DEFAULT_BASE_URL = "http://127.0.0.1:8000";

const TOOL_NAMES = {
  youtube_likes_list_recent: "youtube.likes.list_recent",
  youtube_likes_search_recent_content: "youtube.likes.search_recent_content",
  youtube_transcript_get: "youtube.transcript.get",
  vault_recipe_save: "vault.recipe.save",
  vault_note_save: "vault.note.save",
  vault_bucket_list_add: "vault.bucket_list.add",
  vault_bucket_list_prioritize: "vault.bucket_list.prioritize",
  bucket_item_add: "bucket.item.add",
  bucket_item_update: "bucket.item.update",
  bucket_item_complete: "bucket.item.complete",
  bucket_item_search: "bucket.item.search",
  bucket_item_recommend: "bucket.item.recommend",
  bucket_health_report: "bucket.health.report",
  memory_create: "memory.create",
  memory_undo: "memory.undo",
  reminder_schedule: "reminder.schedule",
  context_suggest_for_query: "context.suggest_for_query",
  digest_weekly_learning_generate: "digest.weekly_learning.generate",
  review_routine_generate: "review.routine.generate",
  recipe_extract_from_transcript: "recipe.extract_from_transcript",
  summary_extract_key_ideas: "summary.extract_key_ideas",
  actions_extract_from_notes: "actions.extract_from_notes",
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
  },
) {
  const extraArgs = options?.extraArgs ?? {};
  const payloadFields = options?.payloadFields ?? [];

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
  "List recently liked YouTube videos; use this for user requests like watched/saw/seen videos and filter by query/topic.",
  {
    extraArgs: {
      limit: tool.schema.any().optional().describe("Maximum number of liked videos to fetch."),
      query: tool.schema
        .string()
        .optional()
        .describe("Filter liked videos by title/content topic."),
      topic: tool.schema
        .string()
        .optional()
        .describe("Alias for query."),
    },
    payloadFields: ["limit", "query", "topic"],
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

export const vault_recipe_save = backendTool(
  TOOL_NAMES.vault_recipe_save,
  "Save a recipe document into the vault.",
);

export const vault_note_save = backendTool(
  TOOL_NAMES.vault_note_save,
  "Save a general note document into the vault.",
);

export const vault_bucket_list_add = backendTool(
  TOOL_NAMES.vault_bucket_list_add,
  "Add an item to the bucket list vault.",
);

export const vault_bucket_list_prioritize = backendTool(
  TOOL_NAMES.vault_bucket_list_prioritize,
  "Get bucket list prioritization from backend context.",
);

export const bucket_item_add = backendTool(
  TOOL_NAMES.bucket_item_add,
  "Add or merge a structured bucket item with optional metadata enrichment.",
);

export const bucket_item_update = backendTool(
  TOOL_NAMES.bucket_item_update,
  "Update a structured bucket item. Include item_id plus changed fields.",
);

export const bucket_item_complete = backendTool(
  TOOL_NAMES.bucket_item_complete,
  "Mark a structured bucket item as completed (kept in storage but hidden from active views).",
);

export const bucket_item_search = backendTool(
  TOOL_NAMES.bucket_item_search,
  "Search structured bucket items by query/domain/genre/duration/rating.",
);

export const bucket_item_recommend = backendTool(
  TOOL_NAMES.bucket_item_recommend,
  "Recommend best-fit bucket items from constraints such as genre and duration.",
);

export const bucket_health_report = backendTool(
  TOOL_NAMES.bucket_health_report,
  "Generate bucket health diagnostics including stale items, metadata gaps, and quick wins.",
);

export const memory_create = backendTool(
  TOOL_NAMES.memory_create,
  "Create a persistent memory entry with undo support.",
);

export const memory_undo = backendTool(
  TOOL_NAMES.memory_undo,
  "Undo a memory entry using undo_token.",
);

export const reminder_schedule = backendTool(
  TOOL_NAMES.reminder_schedule,
  "Schedule a reminder job in backend storage.",
);

export const context_suggest_for_query = backendTool(
  TOOL_NAMES.context_suggest_for_query,
  "Get context-aware suggestions for a user query.",
);

export const digest_weekly_learning_generate = backendTool(
  TOOL_NAMES.digest_weekly_learning_generate,
  "Generate and save the weekly learning digest.",
);

export const review_routine_generate = backendTool(
  TOOL_NAMES.review_routine_generate,
  "Generate and save the routine review artifact.",
);

export const recipe_extract_from_transcript = backendTool(
  TOOL_NAMES.recipe_extract_from_transcript,
  "Extract structured recipe data from transcript text.",
);

export const summary_extract_key_ideas = backendTool(
  TOOL_NAMES.summary_extract_key_ideas,
  "Extract key ideas summary from transcript text.",
);

export const actions_extract_from_notes = backendTool(
  TOOL_NAMES.actions_extract_from_notes,
  "Extract actionable tasks from notes.",
);
