"""Benchmark: the same prompts on both agent engines, compared on speed and correctness.

Runs against the real API over HTTP (so SSE, the MCP server and Ollama are all included):

    uv run ledgerly-seed                        # fresh data, so runs are comparable
    uv run ledgerly-bench-agents --repeats 3    # API, MCP server and Ollama must be running

For each repeat, every prompt in evals/datasets/agent-prompts.json is sent once to each engine.
The engine order alternates per repeat, so neither engine always gets the warmer cache.
One warm-up chat per engine runs first and is not counted (it loads the model).

Fair comparison: same model, prompt, tools, temperature 0 and fixed seed (set in the API's .env).
The number to compare is overheadMs: total time minus time in the model and in tools.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ledgerly.config import REPO_ROOT, get_settings

DEFAULT_DATASET = REPO_ROOT / "evals" / "datasets" / "agent-prompts.json"
ENGINES = ("plain", "langgraph")


# httpx.Client, or the FastAPI TestClient in tests (same methods, different library).
HttpClient = Any
# ---------- One run ----------


@dataclass
class RunResult:
    prompt_id: str
    engine: str
    repeat: int
    ok: bool  # every expectation in the dataset was met
    failures: list[str]
    stop: str
    tools: list[str]
    answer: str
    client_ms: float  # measured here, includes HTTP
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def parse_sse_lines(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """Turn SSE lines into {"event": ..., **data} dicts."""
    event: str | None = None
    for line in lines:
        if line.startswith("event: "):
            event = line[len("event: ") :]
        elif line.startswith("data: ") and event is not None:
            yield {"event": event, **json.loads(line[len("data: ") :])}
            event = None


def score(prompt: dict[str, Any], events: Sequence[dict[str, Any]]) -> list[str]:
    """Check one run against the dataset's expectations. Returns what failed (empty = correct)."""
    expected = prompt.get("expected", {})
    tools = [e["name"] for e in events if e["event"] == "tool_call"]
    answer = "".join(e["text"] for e in events if e["event"] == "token").lower()
    failures: list[str] = []

    for tool in expected.get("tools", []):
        if tool not in tools:
            failures.append(f"did not call {tool}")
    for tool in expected.get("mustNotCall", []):
        if tool in tools:
            failures.append(f"called {tool}")
    for word in expected.get("answerMentions", []):
        if word.lower() not in answer:
            failures.append(f"answer does not mention {word!r}")

    previews = [e["preview"] for e in events if e["event"] == "approval_required"]
    if "recordCount" in expected:
        if expected["recordCount"] == 0:
            if previews:
                failures.append("made a preview but should not have")
        elif not previews:
            failures.append("made no preview")
        elif previews[-1].get("recordCount") != expected["recordCount"]:
            failures.append(
                f"preview has {previews[-1].get('recordCount')} records, expected {expected['recordCount']}"
            )
    if "batchId" in expected:
        undone = [e for e in events if e["event"] == "tool_call" and e["name"] == "undo_batch"]
        if not any(e["arguments"].get("batch_id") == expected["batchId"] for e in undone):
            failures.append(f"did not undo {expected['batchId']}")
    if any(e["event"] == "error" for e in events):
        failures.append("the run ended with an error")
    return failures


def run_once(client: HttpClient, token: str, engine: str, prompt: dict[str, Any], repeat: int) -> RunResult:
    body: dict[str, Any] = {"message": prompt["input"]}
    if prompt.get("folderId"):
        body["folderId"] = prompt["folderId"]
    headers = {"Authorization": f"Bearer {token}", "X-Agent-Engine": engine}

    started = time.perf_counter()
    with client.stream("POST", "/api/agent/chat", json=body, headers=headers) as response:
        if response.status_code != 200:
            response.read()
            raise RuntimeError(f"{engine}: chat returned {response.status_code}: {response.text}")
        events = list(parse_sse_lines(response.iter_lines()))
    client_ms = (time.perf_counter() - started) * 1000

    done = events[-1] if events and events[-1]["event"] == "done" else {}
    failures = score(prompt, events)
    return RunResult(
        prompt_id=prompt["id"],
        engine=engine,
        repeat=repeat,
        ok=not failures,
        failures=failures,
        stop=done.get("stop", "missing"),
        tools=[e["name"] for e in events if e["event"] == "tool_call"],
        answer="".join(e["text"] for e in events if e["event"] == "token"),
        client_ms=round(client_ms, 1),
        metrics=done.get("metrics", {}),
        errors=[e["message"] for e in events if e["event"] == "error"],
    )


# ---------- Many runs ----------


def percentile(values: Sequence[float], pct: float) -> float | None:
    """Linear interpolation between the closest ranks (same as numpy's default)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct / 100
    low, high = math.floor(rank), math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize(results: Sequence[RunResult]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for engine in sorted({r.engine for r in results}):
        runs = [r for r in results if r.engine == engine]

        def metric(name: str, runs: list[RunResult] = runs) -> list[float]:
            return [float(r.metrics[name]) for r in runs if r.metrics.get(name) is not None]

        stats: dict[str, Any] = {"runs": len(runs), "correct": sum(r.ok for r in runs)}
        for name in ("totalMs", "timeToFirstTokenMs", "overheadMs", "modelMs", "toolMs"):
            values = metric(name)
            stats[name] = {"p50": percentile(values, 50), "p95": percentile(values, 95)}
        for name in ("llmCalls", "toolCalls", "promptTokens", "outputTokens"):
            values = metric(name)
            stats[f"avg{name[0].upper()}{name[1:]}"] = round(statistics.fmean(values), 1) if values else None
        summary[engine] = stats
    return summary


def print_report(results: Sequence[RunResult], summary: dict[str, dict[str, Any]]) -> None:
    def ms(value: float | None) -> str:
        return "-" if value is None else f"{value:,.0f}"

    print("\nSpeed (ms, p50 / p95)")
    print(f"{'engine':<10} {'runs':>4} {'total':>17} {'first token':>17} {'model':>17} {'tools':>13} {'overhead':>13}")
    for engine, s in summary.items():
        cells = [
            f"{ms(s[name]['p50'])} / {ms(s[name]['p95'])}"
            for name in ("totalMs", "timeToFirstTokenMs", "modelMs", "toolMs", "overheadMs")
        ]
        print(f"{engine:<10} {s['runs']:>4} {cells[0]:>17} {cells[1]:>17} {cells[2]:>17} {cells[3]:>13} {cells[4]:>13}")

    print("\nWork per run (average)")
    print(f"{'engine':<10} {'LLM calls':>9} {'tool calls':>10} {'prompt tok':>10} {'output tok':>10} {'correct':>9}")
    for engine, s in summary.items():
        print(
            f"{engine:<10} {s['avgLlmCalls']!s:>9} {s['avgToolCalls']!s:>10} {s['avgPromptTokens']!s:>10} "
            f"{s['avgOutputTokens']!s:>10} {s['correct']:>4}/{s['runs']:<4}"
        )

    print("\nCorrectness per prompt (correct runs / runs)")
    engines = list(summary)
    print(f"{'prompt':<24} " + " ".join(f"{e:>10}" for e in engines))
    for prompt_id in dict.fromkeys(r.prompt_id for r in results):
        cells = []
        for engine in engines:
            runs = [r for r in results if r.prompt_id == prompt_id and r.engine == engine]
            cells.append(f"{sum(r.ok for r in runs)}/{len(runs)}")
        print(f"{prompt_id:<24} " + " ".join(f"{c:>10}" for c in cells))

    failed = [r for r in results if not r.ok]
    if failed:
        print("\nWhat went wrong")
        for r in failed:
            print(f"  {r.prompt_id} [{r.engine} #{r.repeat}]: {'; '.join(r.failures)}")

    if {"plain", "langgraph"} <= set(summary):
        plain, graph = summary["plain"]["overheadMs"]["p50"], summary["langgraph"]["overheadMs"]["p50"]
        if plain is not None and graph is not None:
            print(f"\nLangGraph adds {graph - plain:+,.1f} ms of overhead per run (p50) compared with the plain loop.")


def benchmark(
    client: HttpClient,
    password: str,
    prompts: Sequence[dict[str, Any]],
    engines: Sequence[str],
    repeats: int,
    warmup: bool = True,
    log: Any = print,
) -> list[RunResult]:
    tokens: dict[str, str] = {}

    def token_for(user_id: str) -> str:
        if user_id not in tokens:
            email = f"{user_id.removeprefix('usr_')}@ledgerly.test"
            response = client.post("/api/auth/login", json={"email": email, "password": password})
            if response.status_code != 200:
                raise RuntimeError(f"Login failed for {email}: {response.status_code} {response.text}")
            tokens[user_id] = response.json()["accessToken"]
        return tokens[user_id]

    if warmup:
        for engine in engines:
            log(f"warm-up: {engine}")
            run_once(client, token_for(prompts[0]["user"]), engine, {"id": "warm-up", "input": "hi"}, 0)

    results: list[RunResult] = []
    for repeat in range(1, repeats + 1):
        order = list(engines) if repeat % 2 else list(reversed(engines))  # alternate who goes first
        for prompt in prompts:
            for engine in order:
                result = run_once(client, token_for(prompt["user"]), engine, prompt, repeat)
                mark = "ok  " if result.ok else "FAIL"
                total = result.metrics.get("totalMs", result.client_ms)
                log(f"[{repeat}/{repeats}] {mark} {engine:<9} {prompt['id']:<24} {total:>10,.0f} ms")
                results.append(result)
    return results


def load_prompts(path: Path, only: Sequence[str], skip: Sequence[str]) -> list[dict[str, Any]]:
    prompts: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    if only:
        prompts = [p for p in prompts if p["id"] in only]
    prompts = [p for p in prompts if p["id"] not in skip]
    if not prompts:
        raise SystemExit("No prompts left to run. Check --only / --skip.")
    return prompts


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Compare the agent engines on speed and correctness.")
    parser.add_argument("--base-url", default=settings.api_public_url, help="API URL (default: API_PUBLIC_URL)")
    parser.add_argument("--repeats", type=int, default=3, help="times each prompt runs on each engine")
    parser.add_argument("--engines", default=",".join(ENGINES), help="comma-separated, default: plain,langgraph")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--only", default="", help="comma-separated prompt IDs to run")
    parser.add_argument("--skip", default="", help="comma-separated prompt IDs to leave out")
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--out", type=Path, help="also write every run and the summary to this JSON file")
    parser.add_argument("--timeout", type=float, default=600, help="seconds per chat (CPU models are slow)")
    args = parser.parse_args(argv)

    if settings.seed_demo_password is None:
        raise SystemExit("SEED_DEMO_PASSWORD is not set in backend/.env; the benchmark logs in as the demo users.")
    prompts = load_prompts(args.dataset, _split(args.only), _split(args.skip))
    engines = _split(args.engines)

    print(f"{len(prompts)} prompts x {len(engines)} engines x {args.repeats} repeats against {args.base_url}")
    print(f"model {settings.ollama_chat_model}, temperature {settings.agent_temperature}, seed {settings.agent_seed}")
    with httpx.Client(base_url=args.base_url, timeout=httpx.Timeout(args.timeout, connect=10)) as client:
        try:
            client.get("/api/health").raise_for_status()
        except httpx.HTTPError as exc:
            raise SystemExit(f"The API is not reachable at {args.base_url}: {exc}") from None
        results = benchmark(
            client,
            settings.seed_demo_password.get_secret_value(),
            prompts,
            engines,
            args.repeats,
            warmup=not args.no_warmup,
        )

    summary = summarize(results)
    print_report(results, summary)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "model": settings.ollama_chat_model,
            "repeats": args.repeats,
            "summary": summary,
            "runs": [asdict(r) for r in results],
        }
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nWrote {args.out}")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
