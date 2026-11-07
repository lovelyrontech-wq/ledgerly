import { tokenStore } from "@/lib/auth/token-store";
import { env } from "@/lib/env";

/**
 * The agent endpoints (/api/agent/chat and /approve) answer with Server-Sent Events.
 * EventSource only supports GET without headers, so we POST with fetch and parse the stream.
 * Event shapes match backend/src/ledgerly/agent/base.py.
 */

export type AgentMetrics = {
  totalMs: number;
  timeToFirstTokenMs: number | null;
  llmCalls: number;
  toolCalls: number;
  promptTokens: number;
  outputTokens: number;
  modelMs: number;
  llmWallMs: number;
  toolMs: number;
  overheadMs: number;
};

export type AgentEvent =
  | { type: "token"; text: string }
  | { type: "tool_call"; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; name: string; ok: boolean; result: Record<string, unknown>; durationMs: number }
  | { type: "approval_required"; batchId: string; preview: Record<string, unknown> }
  | { type: "error"; message: string }
  | {
      type: "done";
      conversationId: string;
      engine: string;
      stop: "answer" | "approval_required" | "applied" | "max_steps" | "error";
      pendingBatchId: string | null;
      metrics: Partial<AgentMetrics>;
    };

export type AgentEngine = "plain" | "langgraph";

/** Splits an SSE text stream into events. Handles events split across network chunks. */
export function createSseParser(onEvent: (event: AgentEvent) => void) {
  let buffer = "";
  return {
    push(chunk: string) {
      buffer += chunk.replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const data = block
          .split("\n")
          .filter((line) => line.startsWith("data: "))
          .map((line) => line.slice(6))
          .join("\n");
        if (data) onEvent(JSON.parse(data) as AgentEvent);
      }
    },
  };
}

export class AgentRequestError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function streamAgent(
  path: "/api/agent/chat" | "/api/agent/approve",
  body: Record<string, unknown>,
  onEvent: (event: AgentEvent) => void,
  options: { engine?: AgentEngine; signal?: AbortSignal } = {},
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json", Accept: "text/event-stream" };
  const session = tokenStore.get();
  if (session) headers.Authorization = `Bearer ${session.accessToken}`;
  if (options.engine) headers["X-Agent-Engine"] = options.engine;

  const response = await fetch(`${env.apiUrl}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: options.signal,
  });
  if (!response.ok || !response.body) {
    if (response.status === 401) tokenStore.clear();
    const detail = await response
      .json()
      .then((json: { detail?: string }) => json.detail)
      .catch(() => undefined);
    throw new AgentRequestError(response.status, detail ?? `Request failed (${response.status})`);
  }

  const parser = createSseParser(onEvent);
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parser.push(value);
  }
}

export function sendChat(
  input: { message: string; conversationId?: string; folderId?: string },
  onEvent: (event: AgentEvent) => void,
  options?: { engine?: AgentEngine; signal?: AbortSignal },
) {
  return streamAgent("/api/agent/chat", input, onEvent, options);
}

export function approveBatch(
  input: { conversationId: string; batchId: string },
  onEvent: (event: AgentEvent) => void,
  options?: { signal?: AbortSignal },
) {
  return streamAgent("/api/agent/approve", input, onEvent, options);
}
