import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAssistant } from "@/components/agent/use-assistant";
import type { AgentEvent } from "@/lib/api/agent-stream";

// Scripted agent: each test says which events the next request streams back.
const script = vi.hoisted(() => ({ events: [] as AgentEvent[], calls: [] as unknown[] }));
const undoPost = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api/agent-stream", () => {
  const play = async (input: unknown, onEvent: (e: AgentEvent) => void, options?: unknown) => {
    script.calls.push({ input, options });
    for (const event of script.events) onEvent(event);
  };
  return { sendChat: play, approveBatch: play };
});
vi.mock("@/lib/api/client", () => ({ api: { POST: undoPost } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const done = (stop: "answer" | "approval_required" | "applied"): AgentEvent => ({
  type: "done",
  conversationId: "conv_1",
  engine: "plain",
  stop,
  pendingBatchId: stop === "approval_required" ? "bat_1" : null,
  metrics: { totalMs: 1200, overheadMs: 3 },
});

function setup() {
  const queryClient = new QueryClient();
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const hook = renderHook(({ folderId }) => useAssistant(folderId), { wrapper, initialProps: { folderId: "fld_1" } });
  return { ...hook, invalidate };
}

describe("useAssistant", () => {
  beforeEach(() => {
    script.events = [];
    script.calls = [];
    undoPost.mockReset();
  });

  it("streams tokens and tool steps into one assistant message with metrics", async () => {
    script.events = [
      { type: "tool_call", name: "list_records", arguments: {} },
      { type: "tool_result", name: "list_records", ok: true, result: {}, durationMs: 12 },
      { type: "token", text: "There are " },
      { type: "token", text: "3 overdue." },
      done("answer"),
    ];
    const { result } = setup();
    await act(() => result.current.send("How many overdue?"));

    const [user, reply] = result.current.messages;
    expect(user).toMatchObject({ role: "user", text: "How many overdue?" });
    expect(reply).toMatchObject({
      role: "assistant",
      text: "There are 3 overdue.",
      tools: [{ name: "list_records", ok: true, durationMs: 12 }],
      engine: "plain",
      metrics: { totalMs: 1200 },
      streaming: false,
    });
    expect(result.current.busy).toBe(false);
  });

  it("sends the engine only when a conversation starts", async () => {
    script.events = [done("answer")];
    const { result } = setup();
    act(() => result.current.setEngine("langgraph"));
    await act(() => result.current.send("hi"));
    await act(() => result.current.send("again"));

    expect(script.calls[0]).toMatchObject({ input: { folderId: "fld_1" }, options: { engine: "langgraph" } });
    expect(script.calls[1]).toMatchObject({ input: { conversationId: "conv_1" }, options: { engine: undefined } });
  });

  it("shows a preview, applies it on approve, refreshes records, then undoes", async () => {
    const preview = { batchId: "bat_1", instruction: "+10%", recordCount: 2, changes: [] };
    script.events = [{ type: "approval_required", batchId: "bat_1", preview }, done("approval_required")];
    const { result, invalidate } = setup();
    await act(() => result.current.send("raise drafts 10%"));
    expect(result.current.messages[1]).toMatchObject({ approval: { batchId: "bat_1" } });

    script.events = [
      { type: "tool_call", name: "apply_bulk_update", arguments: { batch_id: "bat_1" } },
      { type: "tool_result", name: "apply_bulk_update", ok: true, result: { ...preview, status: "applied" }, durationMs: 40 },
      { type: "token", text: "Done." },
      done("applied"),
    ];
    await act(() => result.current.approve("bat_1"));

    expect(script.calls[1]).toMatchObject({ input: { conversationId: "conv_1", batchId: "bat_1" } });
    expect(result.current.messages[1]).not.toHaveProperty("approval.batchId"); // no longer pending
    expect(result.current.messages[2]).toMatchObject({ applied: { batchId: "bat_1", status: "applied" } });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["records", "fld_1"] });

    undoPost.mockResolvedValue({ data: { batchId: "bat_1", message: "Undone" }, error: undefined });
    await act(() => result.current.undo("bat_1"));
    expect(undoPost).toHaveBeenCalledWith("/api/agent/undo", { body: { conversationId: "conv_1", batchId: "bat_1" } });
    expect(result.current.messages[2]).toMatchObject({ undone: true });
  });

  it("keeps a request error on the message", async () => {
    const { result } = setup();
    script.events = [];
    const agent = await import("@/lib/api/agent-stream");
    vi.spyOn(agent, "sendChat").mockRejectedValueOnce(new Error("Engine langgraph is not enabled"));
    await act(() => result.current.send("hi"));
    expect(result.current.messages[1]).toMatchObject({ error: "Engine langgraph is not enabled", streaming: false });
  });

  it("starts over when the folder changes", async () => {
    script.events = [done("answer")];
    const { result, rerender } = setup();
    await act(() => result.current.send("hi"));
    expect(result.current.messages).toHaveLength(2);
    rerender({ folderId: "fld_2" });
    await waitFor(() => expect(result.current.messages).toHaveLength(0));
  });
});
