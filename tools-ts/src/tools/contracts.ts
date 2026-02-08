export type ToolName =
  | "youtube.likes.list_recent"
  | "youtube.transcript.get"
  | "vault.recipe.save"
  | "vault.note.save"
  | "vault.bucket_list.add"
  | "vault.bucket_list.prioritize"
  | "memory.create"
  | "memory.undo"
  | "reminder.schedule"
  | "context.suggest_for_query"
  | "digest.weekly_learning.generate"
  | "review.routine.generate"
  | "recipe.extract_from_transcript"
  | "summary.extract_key_ideas"
  | "actions.extract_from_notes";

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
