"use client";

import {
  ArrowUp,
  Check,
  CircleAlert,
  Gauge,
  Loader2,
  RotateCcw,
  Sparkles,
  Square,
  SquarePen,
  Wrench,
} from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { AgentEngine, AgentMetrics } from "@/lib/api/agent-stream";
import { cn } from "@/lib/utils";

import type { Assistant, BatchView, ChatMessage } from "./use-assistant";

const ENGINES: { value: AgentEngine; label: string }[] = [
  { value: "plain", label: "Plain" },
  { value: "langgraph", label: "LangGraph" },
];

const SUGGESTIONS = [
  "How many records are overdue?",
  "Raise all draft invoices by 10%",
  "How do I undo a bulk change?",
];

const ms = (value: number | null | undefined) =>
  value == null ? "–" : value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;

function MetricsBadge({ engine, metrics }: { engine?: string; metrics: Partial<AgentMetrics> }) {
  const rows: [string, string][] = [
    ["Total", ms(metrics.totalMs)],
    ["First token", ms(metrics.timeToFirstTokenMs)],
    ["Model (Ollama)", ms(metrics.modelMs)],
    ["LLM wall time", ms(metrics.llmWallMs)],
    ["Tools", ms(metrics.toolMs)],
    ["Engine overhead", ms(metrics.overheadMs)],
    ["LLM / tool calls", `${metrics.llmCalls ?? 0} / ${metrics.toolCalls ?? 0}`],
    ["Tokens in / out", `${metrics.promptTokens ?? 0} / ${metrics.outputTokens ?? 0}`],
  ];
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Badge variant="outline" className="cursor-default gap-1 font-normal text-muted-foreground tabular-nums" />
        }
      >
        <Gauge className="size-3" />
        {engine} · {ms(metrics.totalMs)} · overhead {ms(metrics.overheadMs)}
      </TooltipTrigger>
      <TooltipContent className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-xs tabular-nums">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <span className="opacity-70">{label}</span>
            <span className="text-right">{value}</span>
          </div>
        ))}
      </TooltipContent>
    </Tooltip>
  );
}

/** Shown while the model works. On a CPU-only machine the first word can take 30 s or more. */
function Thinking({ label }: { label: string }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
      <Loader2 className="size-4 animate-spin" />
      <span>
        {label}… <span className="tabular-nums">{seconds}s</span>
      </span>
      {seconds >= 15 && <span className="text-xs">(the local model is slow on CPU; this can take a minute)</span>}
    </div>
  );
}

function BatchCard({
  batch,
  tone,
  children,
}: {
  batch: BatchView;
  tone: "pending" | "applied" | "undone";
  children?: React.ReactNode;
}) {
  const changes = batch.changes ?? [];
  return (
    <div
      className={cn(
        "mt-2 grid gap-2 rounded-xl border bg-card p-3 text-xs shadow-sm",
        tone === "pending" && "border-warning/40 bg-warning/5",
        tone === "applied" && "border-success/30 bg-success/5",
        tone === "undone" && "opacity-70",
      )}
    >
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-medium">
          {tone === "pending" ? "Preview" : tone === "applied" ? "Applied" : "Undone"}: {batch.instruction}
        </span>
        <span className="text-muted-foreground">
          {batch.recordCount} record{batch.recordCount === 1 ? "" : "s"}
        </span>
      </div>
      {batch.totalBefore && (
        <p className="tabular-nums">
          Total {batch.totalBefore} → <span className="font-medium">{batch.totalAfter}</span>
        </p>
      )}
      {changes.length > 0 && (
        <ul className="grid max-h-40 gap-0.5 overflow-y-auto font-mono text-[0.7rem] tabular-nums">
          {changes.map((c) => (
            <li key={c.recordId} className="flex gap-2">
              <span className="min-w-0 flex-1 truncate">{c.name}</span>
              <span className="text-muted-foreground">{c.before}</span>
              <span>→ {c.after}</span>
            </li>
          ))}
          {!!batch.changesNotShown && <li className="text-muted-foreground">…and {batch.changesNotShown} more</li>}
        </ul>
      )}
      {children && <div className="flex flex-wrap gap-2">{children}</div>}
    </div>
  );
}

function AssistantBubble({
  message,
  assistant,
  isPending,
}: {
  message: Extract<ChatMessage, { role: "assistant" }>;
  assistant: Assistant;
  isPending: (batchId: string) => boolean;
}) {
  const [undoing, setUndoing] = useState(false);
  return (
    <div className="flex gap-2.5">
      <span className="brand-gradient mt-0.5 grid size-6 shrink-0 place-items-center rounded-lg text-white" aria-hidden>
        <Sparkles className="size-3.5" />
      </span>
      <div className="grid min-w-0 flex-1 gap-1.5">
        {message.tools.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {message.tools.map((tool, i) => (
              <Badge key={i} variant="secondary" className="gap-1 font-mono text-[0.7rem] font-normal">
                {tool.ok === undefined ? (
                  <Loader2 className="size-3 animate-spin" />
                ) : tool.ok ? (
                  <Wrench className="size-3" />
                ) : (
                  <CircleAlert className="size-3 text-destructive" />
                )}
                {tool.name}
                {tool.durationMs != null && <span className="opacity-60">{ms(tool.durationMs)}</span>}
              </Badge>
            ))}
          </div>
        )}

        {message.streaming && !message.text && (
          // Remounts (and restarts its timer) when the agent moves from a tool back to the model.
          <Thinking
            key={message.tools.length}
            label={message.tools.some((t) => t.ok === undefined) ? "Running a tool" : "Thinking"}
          />
        )}

        {message.text && (
          <div className="text-sm leading-relaxed whitespace-pre-wrap">
            {message.text}
            {message.streaming && (
              <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-foreground/60 align-text-bottom" />
            )}
          </div>
        )}

        {message.approval && (
          <BatchCard batch={message.approval} tone="pending">
            <Button
              size="sm"
              onClick={() => assistant.approve(message.approval!.batchId)}
              disabled={assistant.busy || !isPending(message.approval.batchId)}
            >
              <Check />
              Approve
            </Button>
            <span className="self-center text-muted-foreground">Nothing changes until you approve.</span>
          </BatchCard>
        )}

        {message.applied && (
          <BatchCard batch={message.applied} tone={message.undone ? "undone" : "applied"}>
            {!message.undone && (
              <Button
                size="sm"
                variant="outline"
                disabled={undoing}
                onClick={async () => {
                  setUndoing(true);
                  try {
                    await assistant.undo(message.applied!.batchId);
                  } finally {
                    setUndoing(false);
                  }
                }}
              >
                {undoing ? <Loader2 className="animate-spin" /> : <RotateCcw />}
                Undo
              </Button>
            )}
          </BatchCard>
        )}

        {message.error && (
          <Alert variant="destructive" className="py-2">
            <CircleAlert />
            <AlertDescription>{message.error}</AlertDescription>
          </Alert>
        )}

        {message.metrics && Object.keys(message.metrics).length > 0 && (
          <div>
            <MetricsBadge engine={message.engine} metrics={message.metrics} />
          </div>
        )}
      </div>
    </div>
  );
}

/** The chat with the agent for one folder: streamed answers, approve, undo, engine toggle and metrics. */
export function AssistantPanel({ assistant }: { assistant: Assistant }) {
  const { messages, busy, engine } = assistant;
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  // Only the newest preview can be approved; older ones were replaced on the server.
  const latestApproval = [...messages].reverse().find((m) => m.role === "assistant" && m.approval);
  const isPending = (batchId: string) =>
    latestApproval?.role === "assistant" && latestApproval.approval?.batchId === batchId;

  const last = messages.at(-1);
  const lastText = last?.role === "assistant" ? last.text.length : 0;
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, lastText]);

  function submit(event?: { preventDefault(): void }) {
    event?.preventDefault();
    if (!draft.trim() || busy) return;
    void assistant.send(draft);
    setDraft("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) submit(event);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <div role="radiogroup" aria-label="Agent engine" className="flex rounded-full bg-muted p-0.5">
          {ENGINES.map((e) => (
            <button
              key={e.value}
              type="button"
              role="radio"
              aria-checked={engine === e.value}
              disabled={busy}
              onClick={() => assistant.setEngine(e.value)}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium text-muted-foreground transition-colors disabled:opacity-50",
                engine === e.value && "bg-background text-foreground shadow-sm",
              )}
            >
              {e.label}
            </button>
          ))}
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          className="ml-auto"
          aria-label="New conversation"
          title="New conversation"
          onClick={assistant.reset}
          disabled={messages.length === 0}
        >
          <SquarePen />
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-4" aria-live="polite">
        {messages.length === 0 ? (
          <div className="grid gap-4 text-sm text-muted-foreground">
            <div className="grid justify-items-start gap-2">
              <span className="brand-gradient grid size-10 place-items-center rounded-2xl text-white shadow-lg shadow-primary/25">
                <Sparkles className="size-5" />
              </span>
              <p className="font-heading text-lg font-semibold text-foreground">How can I help?</p>
              <p>
                Ask about this folder&apos;s records or the app. Bulk changes are shown as a preview first and only
                applied when you approve.
              </p>
            </div>
            <div className="grid gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => assistant.send(s)}
                  disabled={busy}
                  className="rounded-xl border bg-card px-3 py-2 text-left text-sm text-foreground transition-colors hover:border-primary/30 hover:bg-accent/50 disabled:opacity-50"
                >
                  {s}
                </button>
              ))}
            </div>
            <p className="text-xs">
              Switching engine starts a new conversation. Each answer shows its timing; hover it for details.
            </p>
          </div>
        ) : (
          <div className="grid gap-4">
            {messages.map((m) =>
              m.role === "user" ? (
                <div
                  key={m.id}
                  className="brand-gradient ml-auto max-w-[85%] rounded-2xl rounded-br-md px-3.5 py-2 text-sm whitespace-pre-wrap text-white shadow-sm shadow-primary/20"
                >
                  {m.text}
                </div>
              ) : (
                <AssistantBubble key={m.id} message={m} assistant={assistant} isPending={isPending} />
              ),
            )}
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form onSubmit={submit} className="border-t p-3">
        <div className="flex items-end gap-2 rounded-2xl border bg-background p-1.5 shadow-sm transition-colors focus-within:border-primary/40 focus-within:ring-3 focus-within:ring-ring/20">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Message the assistant…"
            aria-label="Message"
            rows={1}
            maxLength={4000}
            className="max-h-32 min-h-9 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent"
          />
          {busy ? (
            <Button
              type="button"
              size="icon"
              variant="outline"
              className="rounded-xl"
              aria-label="Stop"
              onClick={assistant.stop}
            >
              <Square />
            </Button>
          ) : (
            <Button type="submit" size="icon" className="rounded-xl" aria-label="Send" disabled={!draft.trim()}>
              <ArrowUp />
            </Button>
          )}
        </div>
      </form>
    </div>
  );
}
