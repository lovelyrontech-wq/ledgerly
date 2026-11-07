"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { recordsKey } from "@/components/records/use-records";
import {
  approveBatch,
  sendChat,
  type AgentEngine,
  type AgentEvent,
  type AgentMetrics,
} from "@/lib/api/agent-stream";
import { api } from "@/lib/api/client";

/** A bulk-update batch as the MCP tools describe it (preview_bulk_update / apply_bulk_update / undo_batch). */
export type BatchView = {
  batchId: string;
  folderId?: string;
  status?: string;
  instruction?: string;
  recordCount?: number;
  totalBefore?: string;
  totalAfter?: string;
  summary?: Record<string, number>;
  changes?: { recordId: string; name: string; before: string; after: string; result?: string | null }[];
  changesNotShown?: number;
  message?: string;
};

export type ToolStep = { name: string; ok?: boolean; durationMs?: number };

export type ChatMessage =
  | { id: string; role: "user"; text: string }
  | {
      id: string;
      role: "assistant";
      text: string;
      tools: ToolStep[];
      approval?: BatchView; // a preview waiting for the user
      applied?: BatchView; // a batch this turn applied (can be undone)
      undone?: boolean;
      error?: string;
      engine?: string;
      metrics?: Partial<AgentMetrics>;
      streaming: boolean;
    };

type AssistantMessage = Extract<ChatMessage, { role: "assistant" }>;

let nextId = 0;
const newId = () => `m${++nextId}`;

/**
 * One conversation with the agent for a folder. Lives in FolderWorkspace so the desktop column and
 * the phone sheet show the same chat. Changing folder or engine starts a new conversation.
 */
export function useAssistant(folderId: string) {
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [engine, setEngineState] = useState<AgentEngine>("plain");
  const [busy, setBusy] = useState(false);
  const conversationId = useRef<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abort.current?.abort();
    abort.current = null;
    conversationId.current = null;
    setMessages([]);
    setBusy(false);
  }, []);

  // A new folder is a new conversation ("this folder" must mean the one on screen).
  useEffect(() => reset, [folderId, reset]);

  const patch = useCallback((id: string, update: (m: AssistantMessage) => AssistantMessage) => {
    setMessages((all) => all.map((m) => (m.id === id && m.role === "assistant" ? update(m) : m)));
  }, []);

  const refreshRecords = useCallback(
    () => queryClient.invalidateQueries({ queryKey: recordsKey(folderId) }),
    [queryClient, folderId],
  );

  /** Runs one streamed request, writing its events into a fresh assistant message. */
  const run = useCallback(
    async (start: (onEvent: (e: AgentEvent) => void, signal: AbortSignal) => Promise<void>) => {
      const id = newId();
      setMessages((all) => [...all, { id, role: "assistant", text: "", tools: [], streaming: true }]);
      setBusy(true);
      const controller = new AbortController();
      abort.current = controller;
      let changedRecords = false;

      const onEvent = (event: AgentEvent) => {
        switch (event.type) {
          case "token":
            patch(id, (m) => ({ ...m, text: m.text + event.text }));
            break;
          case "tool_call":
            patch(id, (m) => ({ ...m, tools: [...m.tools, { name: event.name }] }));
            break;
          case "tool_result": {
            const batch = event.result as BatchView;
            if (event.ok && (event.name === "apply_bulk_update" || event.name === "undo_batch")) changedRecords = true;
            patch(id, (m) => {
              const tools = [...m.tools];
              const i = tools.findLastIndex((t) => t.name === event.name && t.ok === undefined);
              if (i !== -1) tools[i] = { ...tools[i], ok: event.ok, durationMs: event.durationMs };
              const applied = event.ok && event.name === "apply_bulk_update" ? batch : m.applied;
              return { ...m, tools, applied };
            });
            if (event.ok && event.name === "apply_bulk_update") {
              // The preview is no longer pending once it is applied.
              setMessages((all) =>
                all.map((m) =>
                  m.role === "assistant" && m.approval?.batchId === batch.batchId ? { ...m, approval: undefined } : m,
                ),
              );
            }
            break;
          }
          case "approval_required":
            patch(id, (m) => ({ ...m, approval: { ...(event.preview as BatchView), batchId: event.batchId } }));
            break;
          case "error":
            patch(id, (m) => ({ ...m, error: event.message }));
            break;
          case "done":
            conversationId.current = event.conversationId;
            patch(id, (m) => ({ ...m, engine: event.engine, metrics: event.metrics }));
            break;
        }
      };

      try {
        await start(onEvent, controller.signal);
      } catch (err) {
        if (!controller.signal.aborted) {
          const message = err instanceof Error ? err.message : "Could not reach the assistant";
          patch(id, (m) => ({ ...m, error: message }));
        }
      } finally {
        patch(id, (m) => ({ ...m, streaming: false }));
        if (abort.current === controller) {
          abort.current = null;
          setBusy(false);
        }
        if (changedRecords) void refreshRecords();
      }
    },
    [patch, refreshRecords],
  );

  const send = useCallback(
    (text: string) => {
      const message = text.trim();
      if (!message || busy) return;
      setMessages((all) => [...all, { id: newId(), role: "user", text: message }]);
      const existing = conversationId.current ?? undefined;
      return run((onEvent, signal) =>
        sendChat({ message, conversationId: existing, folderId }, onEvent, {
          // The engine is fixed when the conversation starts; the server keeps it after that.
          engine: existing ? undefined : engine,
          signal,
        }),
      );
    },
    [busy, engine, folderId, run],
  );

  const approve = useCallback(
    (batchId: string) => {
      const id = conversationId.current;
      if (!id || busy) return;
      return run((onEvent, signal) => approveBatch({ conversationId: id, batchId }, onEvent, { signal }));
    },
    [busy, run],
  );

  const undo = useCallback(
    async (batchId: string) => {
      const id = conversationId.current;
      if (!id) return;
      const { data, error } = await api.POST("/api/agent/undo", { body: { conversationId: id, batchId } });
      if (error || !data) {
        toast.error((error as { detail?: string } | undefined)?.detail ?? "Undo failed");
        return;
      }
      setMessages((all) =>
        all.map((m) => (m.role === "assistant" && m.applied?.batchId === batchId ? { ...m, undone: true } : m)),
      );
      const result = data as BatchView;
      toast.success(result.message ?? "Batch undone");
      void refreshRecords();
    },
    [refreshRecords],
  );

  const stop = useCallback(() => abort.current?.abort(), []);

  const setEngine = useCallback(
    (next: AgentEngine) => {
      if (next === engine) return;
      reset(); // a conversation stays on one engine, so switching starts a new one
      setEngineState(next);
    },
    [engine, reset],
  );

  return { messages, engine, setEngine, busy, send, approve, undo, stop, reset };
}

export type Assistant = ReturnType<typeof useAssistant>;
