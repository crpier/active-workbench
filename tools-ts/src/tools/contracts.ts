export type ToolName =
  | "youtube.likes.list_recent"
  | "youtube.likes.search_recent_content"
  | "youtube.transcript.get"
  | "bucket.item.add"
  | "bucket.item.update"
  | "bucket.item.complete"
  | "bucket.item.search"
  | "bucket.item.recommend"
  | "bucket.health.report"
  | "memory.create"
  | "memory.list"
  | "memory.search"
  | "memory.delete"
  | "memory.undo";

export interface ToolContext {
  timezone?: string;
  session_id?: string;
}

export interface ToolEnvelope {
  tool: ToolName;
  request_id: string;
  idempotency_key?: string;
  payload?: Record<string, unknown>;
  context?: ToolContext;
}
