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
  "youtube.likes.list_recent": (request) => ToolsService.youtubeLikesListRecent(request),
  "youtube.likes.search_recent_content": (request) =>
    ToolsService.youtubeLikesSearchRecentContent(request),
  "youtube.watch_later.list": (request) => ToolsService.youtubeWatchLaterList(request),
  "youtube.watch_later.search_content": (request) =>
    ToolsService.youtubeWatchLaterSearchContent(request),
  "youtube.watch_later.recommend": (request) => ToolsService.youtubeWatchLaterRecommend(request),
  "youtube.transcript.get": (request) => ToolsService.youtubeTranscriptGet(request),
  "bucket.item.add": (request) => ToolsService.bucketItemAdd(request),
  "bucket.item.update": (request) => ToolsService.bucketItemUpdate(request),
  "bucket.item.complete": (request) => ToolsService.bucketItemComplete(request),
  "bucket.item.search": (request) => ToolsService.bucketItemSearch(request),
  "bucket.item.recommend": (request) => ToolsService.bucketItemRecommend(request),
  "bucket.health.report": (request) => ToolsService.bucketHealthReport(request),
  "memory.create": (request) => ToolsService.memoryCreate(request),
  "memory.list": (request) => ToolsService.memoryList(request),
  "memory.search": (request) => ToolsService.memorySearch(request),
  "memory.delete": (request) => ToolsService.memoryDelete(request),
  "memory.undo": (request) => ToolsService.memoryUndo(request),
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
