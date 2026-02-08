import { randomUUID } from "node:crypto";

import type { ToolRequest } from "../client";

export interface CreateToolRequestInput {
  tool: ToolRequest["tool"];
  payload?: Record<string, unknown>;
  sessionId?: string;
  timezone?: string;
}

export function createToolRequest(input: CreateToolRequestInput): ToolRequest {
  return {
    tool: input.tool,
    request_id: randomUUID(),
    idempotency_key: randomUUID(),
    payload: input.payload ?? {},
    context: {
      timezone: input.timezone ?? "Europe/Bucharest",
      session_id: input.sessionId,
    },
  };
}
