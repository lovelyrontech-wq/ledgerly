import { describe, expect, it } from "vitest";

import { createSseParser, type AgentEvent } from "@/lib/api/agent-stream";

function collect(chunks: string[]): AgentEvent[] {
  const events: AgentEvent[] = [];
  const parser = createSseParser((event) => events.push(event));
  chunks.forEach((chunk) => parser.push(chunk));
  return events;
}

describe("createSseParser", () => {
  it("parses events in one chunk", () => {
    const body =
      'event: token\ndata: {"type": "token", "text": "Hi"}\n\n' +
      'event: done\ndata: {"type": "done", "conversationId": "conv_1", "engine": "plain", "stop": "answer", "pendingBatchId": null, "metrics": {}}\n\n';
    expect(collect([body]).map((e) => e.type)).toEqual(["token", "done"]);
  });

  it("joins an event split across network chunks", () => {
    const events = collect(['event: token\ndata: {"type": "tok', 'en", "text": "Hel', 'lo"}\n', "\n"]);
    expect(events).toEqual([{ type: "token", text: "Hello" }]);
  });

  it("handles Windows line endings", () => {
    const events = collect(['event: error\r\ndata: {"type": "error", "message": "down"}\r\n\r\n']);
    expect(events).toEqual([{ type: "error", message: "down" }]);
  });

  it("waits for the blank line before emitting", () => {
    expect(collect(['event: token\ndata: {"type": "token", "text": "x"}\n'])).toEqual([]);
  });
});
