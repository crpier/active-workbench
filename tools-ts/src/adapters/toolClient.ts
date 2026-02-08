import {
  OpenAPI,
  ToolsService,
  type ToolCatalogEntry,
  type ToolRequest,
  type ToolResponse,
} from "../client";

export type ToolName = ToolRequest["tool"];

type ToolCall = (request: ToolRequest) => Promise<ToolResponse>;

const TOOL_METHODS: Record<ToolName, ToolCall> = {
  "youtube.history.list_recent": (request) => ToolsService.youtubeHistoryListRecent(request),
  "youtube.transcript.get": (request) => ToolsService.youtubeTranscriptGet(request),
  "vault.recipe.save": (request) => ToolsService.vaultRecipeSave(request),
  "vault.note.save": (request) => ToolsService.vaultNoteSave(request),
  "vault.bucket_list.add": (request) => ToolsService.vaultBucketListAdd(request),
  "memory.create": (request) => ToolsService.memoryCreate(request),
  "memory.undo": (request) => ToolsService.memoryUndo(request),
  "reminder.schedule": (request) => ToolsService.reminderSchedule(request),
  "context.suggest_for_query": (request) => ToolsService.contextSuggestForQuery(request),
  "digest.weekly_learning.generate": (request) =>
    ToolsService.digestWeeklyLearningGenerate(request),
  "review.routine.generate": (request) => ToolsService.reviewRoutineGenerate(request),
  "recipe.extract_from_transcript": (request) =>
    ToolsService.recipeExtractFromTranscript(request),
  "summary.extract_key_ideas": (request) => ToolsService.summaryExtractKeyIdeas(request),
  "actions.extract_from_notes": (request) => ToolsService.actionsExtractFromNotes(request),
};

export interface ToolClientConfig {
  baseUrl: string;
  token?: string;
}

export class ToolClient {
  constructor(config: ToolClientConfig) {
    OpenAPI.BASE = config.baseUrl;
    OpenAPI.TOKEN = config.token;
  }

  async listTools(): Promise<ToolCatalogEntry[]> {
    return ToolsService.listTools();
  }

  async callTool(request: ToolRequest): Promise<ToolResponse> {
    const call = TOOL_METHODS[request.tool];
    return call(request);
  }
}
