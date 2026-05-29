"""Drive the process-inbox skill in a loop by spawning external agent CLIs.

Each iteration spawns a fresh `claude` or `opencode` subprocess that processes
exactly ONE inbox item, following the process-inbox skill (which is auto-loaded
by both CLIs via AGENTS.md). The orchestrator context is therefore also fresh
each item — stricter isolation than the skill's internal subagent approach.

Rate-limit handling: each `AgentConfig` is tried in order. If the active agent
returns a rate-limit signal (non-zero exit + pattern match on output), the
runner advances to the next agent in the list and retries the SAME item.
When the list is exhausted, the runner stops and reports.

The runner has no business logic of its own — `mark-processed`, history log,
and session creation are all done by the spawned agent following AGENTS.md.
"""
from __future__ import annotations

import json
import re
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from cogforge.config import AgentConfig
from cogforge.paths import Paths
from cogforge.prepare import PrepareResult, prepare_inbox_source
from cogforge.state import SourceState, SourceStatus, list_source_states, save_state


# Per-item prompt template. The runner pre-selects the source and injects its
# id/connector/path so the spawned agent skips the "discover what to do" dance.
# AGENTS.md is auto-loaded by both CLIs, so the /process-inbox skill is already
# in context — we just point it at the specific source.
PROMPT_TEMPLATE = (
    "Process inbox source {source_id} ({connector}) at path "
    "{inbox_path} using the /process-inbox skill. "
    "The source has already been pre-validated and prepared by cogforge. "
    "Estimated chars: {estimated_chars}. PageIndex required: {pageindex_required}. "
    "Stop after this single source."
)

# Default rate-limit detection patterns per agent CLI.
# These are matched case-insensitively as substrings of (stdout + stderr).
# Each agent CLI surfaces rate limiting differently — override per-agent in
# sources.yaml via `rate_limit_patterns:` if a CLI's wording changes.
DEFAULT_RATE_LIMIT_PATTERNS: dict[str, list[str]] = {
    "claude": [
        "rate_limit_error",
        "rate limit",
        "429",
        "529",
        "overloaded_error",
        "overloaded",
    ],
    "opencode": [
        "rate limit",
        "rate_limited",
        "429",
        "529",
        "overloaded",
    ],
}


@dataclass
class TokenUsage:
    """Token consumption for one agent invocation (or a cumulative total)."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )

    def is_empty(self) -> bool:
        return self.input_tokens == 0 and self.output_tokens == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cost_usd": self.cost_usd,
        }


class LoopResult(str, Enum):
    """Terminal state of a `run_loop()` invocation."""
    SUCCESS = "success"                       # inbox drained successfully
    INBOX_EMPTY = "inbox_empty"               # inbox was empty when we started; nothing to do
    AGENT_FAILURE = "agent_failure"           # an agent failed with a non-rate-limit error
    ALL_RATE_LIMITED = "all_rate_limited"     # fallback list exhausted
    MAX_ITEMS_REACHED = "max_items_reached"   # --max-items cap hit
    DRY_RUN = "dry_run"                       # dry-run mode, no work performed
    NO_AGENTS = "no_agents"                   # empty agents list


@dataclass
class LoopReport:
    result: LoopResult
    items_processed: int = 0
    items_attempted: int = 0
    agent_index_used_last: int = -1
    failures: list[dict[str, Any]] = field(default_factory=list)
    rate_limit_events: list[dict[str, Any]] = field(default_factory=list)
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    # Per-item structured results (source_id, pages_created, etc.) — populated
    # for claude agents where stdout is captured; empty for opencode.
    items_detail: list[dict[str, Any]] = field(default_factory=list)
    prepare_results: list[dict[str, Any]] = field(default_factory=list)
    # Dry-run payload
    pending_count: int | None = None
    planned_command: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "result": self.result.value,
            "items_processed": self.items_processed,
            "items_attempted": self.items_attempted,
            "agent_index_used_last": self.agent_index_used_last,
            "rate_limit_events": self.rate_limit_events,
            "failures": self.failures,
        }
        if not self.total_usage.is_empty():
            out["total_usage"] = self.total_usage.to_dict()
        if self.items_detail:
            out["items_detail"] = self.items_detail
        if self.prepare_results:
            out["prepare_results"] = self.prepare_results
        if self.pending_count is not None:
            out["pending_count"] = self.pending_count
        if self.planned_command is not None:
            out["planned_command"] = self.planned_command
        return out


# ── internal helpers ─────────────────────────────────────────────────────────


def _count_inbox(paths: Paths) -> int:
    """Return the number of pending inbox items (status == 'inbox')."""
    return len(list_source_states(paths.state_sources, status=SourceStatus.INBOX.value))


def _build_command(agent: AgentConfig, prompt: str = "") -> list[str]:
    """Build the subprocess argv for a single per-item invocation.

    For `claude`: uses --print + --dangerously-skip-permissions so the loop can
    run unattended.
    For `opencode`: uses `run` subcommand (non-interactive by default).
    """
    if agent.cli == "claude":
        cmd = ["claude", "--dangerously-skip-permissions", "--print"]
        if agent.model:
            cmd += ["--model", agent.model]
        cmd += list(agent.extra_args)
        cmd.append(prompt)
        return cmd

    if agent.cli == "opencode":
        cmd = ["opencode", "run"]
        if agent.model:
            cmd += ["--model", agent.model]
        cmd += list(agent.extra_args)
        cmd.append(prompt)
        return cmd

    raise ValueError(f"Unknown agent.cli: {agent.cli!r}")


def _detect_rate_limit(
    agent: AgentConfig, returncode: int, stdout: str, stderr: str
) -> bool:
    """Return True iff the agent output looks like a rate-limit response.

    Requires non-zero exit code AND a case-insensitive substring match against
    the agent's configured patterns (or the per-CLI default list).
    """
    if returncode == 0:
        return False
    patterns = agent.rate_limit_patterns
    if patterns is None:
        patterns = DEFAULT_RATE_LIMIT_PATTERNS.get(agent.cli, [])
    if not patterns:
        return False
    haystack = f"{stdout}\n{stderr}".lower()
    return any(p.lower() in haystack for p in patterns)


def _stream_claude_events(
    proc: "subprocess.Popen[str]", verbose: bool
) -> tuple[TokenUsage, str]:
    """Read stream-json events from proc.stdout, render text to terminal.

    Returns (usage, full_text) where full_text is the concatenation of all
    assistant text blocks — used by the caller to extract structured JSON
    reports embedded in the agent output.

    Text blocks from assistant messages are printed as they arrive (live
    streaming). Tool-use block names are shown only in verbose mode.
    The final `result` event is parsed for cumulative token usage.
    """
    usage = TokenUsage()
    text_parts: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(raw)
            sys.stdout.flush()
            continue

        t = event.get("type")
        if t == "assistant":
            for block in event.get("message", {}).get("content", []):
                bt = block.get("type")
                if bt == "text":
                    text = block.get("text", "")
                    if text:
                        text_parts.append(text)
                        sys.stdout.write(text)
                        if not text.endswith("\n"):
                            sys.stdout.write("\n")
                        sys.stdout.flush()
                elif bt == "tool_use" and verbose:
                    sys.stdout.write(f"  [tool: {block.get('name', '?')}]\n")
                    sys.stdout.flush()
        elif t == "result":
            u = event.get("usage", {})
            usage = TokenUsage(
                input_tokens=u.get("input_tokens", 0),
                output_tokens=u.get("output_tokens", 0),
                cache_read_tokens=u.get("cache_read_input_tokens", 0),
                cost_usd=event.get("cost_usd", 0.0),
            )
    return usage, "".join(text_parts)


def _stream_opencode_stdout(
    proc: "subprocess.Popen[str]",
    patterns: list[str],
    verbose: bool,
) -> tuple[str, bool]:
    """Read opencode stdout line-by-line, echo to terminal, scan for rate-limit.

    Returns (accumulated_text, rate_limited_detected).
    """
    out_lines: list[str] = []
    rate_limited = False
    assert proc.stdout is not None
    for raw in proc.stdout:
        out_lines.append(raw)
        sys.stdout.write(raw)
        sys.stdout.flush()
        if not rate_limited:
            haystack = raw.lower()
            if any(p.lower() in haystack for p in patterns):
                rate_limited = True
                if verbose:
                    print(
                        f"[inbox-run] rate-limit pattern detected in stdout; killing process",
                        file=sys.stderr,
                    )
                proc.kill()
                break
    return "".join(out_lines), rate_limited


def _invoke(
    cmd: list[str], timeout: int, verbose: bool, cwd: Path | None = None
) -> tuple[int, str, str, TokenUsage]:
    """Run the agent CLI and return (returncode, stdout, stderr, usage).

    For `claude`: injects `--output-format stream-json` so stdout is parsed
    for real-time rendering and token extraction. stderr is still captured for
    rate-limit detection.

    For `opencode`: stdout is piped and scanned line-by-line for rate-limit
    patterns. Each line is echoed to the terminal immediately. If a rate-limit
    pattern is found, the process is killed immediately and a synthetic error
    is returned so the runner can fallback to the next agent.

    On timeout or missing binary, returns a synthesized non-zero exit.
    """
    if verbose:
        print(f"[inbox-run] $ {' '.join(cmd[:3])} ... (timeout={timeout}s)", file=sys.stderr)

    is_claude = cmd[0] == "claude"

    item_usage = TokenUsage()
    try:
        if is_claude:
            # Inject --output-format stream-json before the prompt (last arg).
            stream_cmd = cmd[:-1] + ["--output-format", "stream-json", cmd[-1]]
            proc = subprocess.Popen(
                stream_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(cwd) if cwd else None,
            )
            # Kill the process if it exceeds the timeout.
            timed_out = False
            def _kill() -> None:
                nonlocal timed_out
                timed_out = True
                proc.kill()
            timer = threading.Timer(timeout, _kill)
            timer.start()
            try:
                item_usage, out_text = _stream_claude_events(proc, verbose)
                _, stderr_output = proc.communicate()
            finally:
                timer.cancel()
            rc = proc.returncode
            if timed_out:
                return 124, "", f"timeout after {timeout}s", TokenUsage()
        else:
            # opencode: pipe stdout so we can scan for rate-limit patterns
            # in real time, while still echoing each line to the terminal.
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(cwd) if cwd else None,
            )
            timed_out = False
            def _kill() -> None:
                nonlocal timed_out
                timed_out = True
                proc.kill()
            timer = threading.Timer(timeout, _kill)
            timer.start()
            try:
                out_text, rate_limited = _stream_opencode_stdout(
                    proc,
                    patterns=DEFAULT_RATE_LIMIT_PATTERNS.get("opencode", []),
                    verbose=verbose,
                )
                _, stderr_output = proc.communicate()
            finally:
                timer.cancel()
            rc = proc.returncode
            if timed_out:
                return 124, out_text, f"timeout after {timeout}s", TokenUsage()
            if rate_limited:
                # Synthesize a non-zero exit so _detect_rate_limit fires
                return 1, out_text, stderr_output or "rate limited", TokenUsage()

    except subprocess.TimeoutExpired as e:
        return 124, "", f"timeout after {timeout}s: {e}", TokenUsage()
    except FileNotFoundError as e:
        return 127, "", f"agent binary not found: {e}", TokenUsage()

    if stderr_output:
        sys.stderr.write(stderr_output)
        if not stderr_output.endswith("\n"):
            sys.stderr.write("\n")
    return rc, out_text, stderr_output or "", item_usage


def _extract_json_report(text: str) -> dict[str, Any] | None:
    """Try to parse a structured JSON report from agent output.

    Looks for a <RESULT>…</RESULT> sentinel first (preferred), then falls
    back to scanning for the last well-formed JSON object in the text.
    Returns None if no JSON can be found or parsed.
    """
    # Primary: <RESULT>…</RESULT> sentinel
    sentinel = re.search(r"<RESULT>\s*(\{.*?\})\s*</RESULT>", text, re.DOTALL)
    if sentinel:
        try:
            return json.loads(sentinel.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: find the last complete {...} block by balanced-brace scan
    last_close = text.rfind("}")
    if last_close < 0:
        return None
    depth = 0
    start = -1
    for i in range(last_close, -1, -1):
        if text[i] == "}":
            depth += 1
        elif text[i] == "{":
            depth -= 1
            if depth == 0:
                start = i
                break
    if start < 0:
        return None
    try:
        return json.loads(text[start : last_close + 1])
    except (json.JSONDecodeError, ValueError):
        return None


# ── public surface ────────────────────────────────────────────────────────────


def run_loop(
    paths: Paths,
    agents: list[AgentConfig],
    config=None,
    *,
    max_items: int | None = None,
    delay_seconds: float = 2.0,
    dry_run: bool = False,
    verbose: bool = False,
    cwd: Path | None = None,
) -> LoopReport:
    """Drive the process-inbox skill in a loop, one item per agent session.

    Args:
        paths: wiki Paths instance (used to count inbox state files).
        agents: ordered fallback list. agents[0] is tried first; on rate-limit
            we advance to agents[1], etc.
        max_items: stop after N successfully processed items (None = drain).
        delay_seconds: sleep between iterations to avoid hammering the agent CLI.
        dry_run: report what would happen without invoking any subprocess.
        verbose: mirror agent stderr to our own stderr after each call.
        cwd: working directory for the subprocess (default: current).

    Returns:
        LoopReport with terminal LoopResult and metrics.
    """
    if not agents:
        return LoopReport(result=LoopResult.NO_AGENTS)

    if dry_run:
        # The actual prompt is built per-item at runtime (source pre-selected
        # from inbox). Use the template here so the caller can see the shape.
        example_prompt = PROMPT_TEMPLATE.format(
            source_id="<source_id>",
            connector="<connector>",
            inbox_path="<inbox_path>",
            estimated_chars=0,
            pageindex_required="no",
        )
        return LoopReport(
            result=LoopResult.DRY_RUN,
            pending_count=_count_inbox(paths),
            planned_command=_build_command(agents[0], example_prompt),
        )

    items_processed = 0
    items_attempted = 0
    failures: list[dict[str, Any]] = []
    rate_limit_events: list[dict[str, Any]] = []
    items_detail: list[dict[str, Any]] = []
    cumulative_usage = TokenUsage()
    agent_idx = 0

    while True:
        if max_items is not None and items_processed >= max_items:
            return LoopReport(
                result=LoopResult.MAX_ITEMS_REACHED,
                items_processed=items_processed,
                items_attempted=items_attempted,
                agent_index_used_last=agent_idx if items_processed else -1,
                failures=failures,
                rate_limit_events=rate_limit_events,
                total_usage=cumulative_usage,
                items_detail=items_detail,
            )

        if agent_idx >= len(agents):
            return LoopReport(
                result=LoopResult.ALL_RATE_LIMITED,
                items_processed=items_processed,
                items_attempted=items_attempted,
                agent_index_used_last=len(agents) - 1,
                failures=failures,
                rate_limit_events=rate_limit_events,
                total_usage=cumulative_usage,
                items_detail=items_detail,
            )

        # Pre-select the next pending source. This also serves as the
        # empty-inbox check and eliminates the per-item "discover what to do"
        # dance inside the spawned agent session.
        inbox_sources = list_source_states(
            paths.state_sources, status=SourceStatus.INBOX.value
        )
        pending = len(inbox_sources)
        if pending == 0:
            result = LoopResult.SUCCESS if items_processed else LoopResult.INBOX_EMPTY
            return LoopReport(
                result=result,
                items_processed=items_processed,
                items_attempted=items_attempted,
                agent_index_used_last=agent_idx if items_processed else -1,
                failures=failures,
                rate_limit_events=rate_limit_events,
                total_usage=cumulative_usage,
                items_detail=items_detail,
            )
        next_source: SourceState = inbox_sources[0]

        agent = agents[agent_idx]
        items_attempted += 1

        # Prominent per-item header — always printed regardless of verbose.
        label = f"  item {items_processed + 1}"
        if max_items:
            label += f" of {max_items}"
        label += f"  |  agent: {agent.cli}"
        if agent.model:
            label += f" / {agent.model}"
        label += f"  |  {pending} remaining  "
        bar = "─" * max(len(label), 60)
        print(f"\n{bar}", file=sys.stderr)
        print(label, file=sys.stderr)
        print(bar, file=sys.stderr)

        if verbose:
            print(
                f"[inbox-run] attempt #{items_attempted}: "
                f"agent[{agent_idx}] cli={agent.cli} model={agent.model or '<default>'} "
                f"source={next_source.id} ({pending} pending)",
                file=sys.stderr,
            )

        # Build a per-item prompt that names the specific source so the agent
        # skips the inbox-discovery dance.
        # Force prepare before spawning agent
        from loguru import logger
        from cogforge.config import Config
        effective_config = config if config is not None else Config()
        prepare_result = prepare_inbox_source(
            next_source.id, paths, effective_config,
            no_pageindex=False,
            no_pdf_enrich=False,
        )
        logger.info(json.dumps({
            "phase": "prepare",
            "source_id": next_source.id,
            "package_valid": prepare_result.package_valid,
            "long_document": prepare_result.long_document_detected,
        }))

        if not prepare_result.package_valid:
            failures.append({
                "attempt": items_attempted,
                "agent_index": agent_idx,
                "agent_cli": "prepare",
                "returncode": 1,
                "reason": f"Package invalid: {', '.join(prepare_result.package_issues)}",
            })
            # Mark source as failed so we don't retry it infinitely
            next_source.status = SourceStatus.FAILED.value
            save_state(paths.state_sources, next_source)
            items_detail.append({
                "source_id": next_source.id,
                "connector": next_source.connector,
                "prepare_failed": True,
                "prepare_issues": prepare_result.package_issues,
            })
            continue

        prompt = PROMPT_TEMPLATE.format(
            source_id=next_source.id,
            connector=next_source.connector,
            inbox_path=next_source.paths.inbox or "(no inbox path)",
            estimated_chars=next_source.content.estimated_chars or 0,
            pageindex_required="yes" if prepare_result.long_document_detected else "no",
        )
        cmd = _build_command(agent, prompt)
        rc, out, err, item_usage = _invoke(cmd, agent.timeout_seconds, verbose, cwd=cwd)

        if _detect_rate_limit(agent, rc, out, err):
            event = {
                "attempt": items_attempted,
                "agent_index": agent_idx,
                "agent_cli": agent.cli,
                "agent_model": agent.model,
                "returncode": rc,
                "stderr_excerpt": (err or out)[-500:],
            }
            rate_limit_events.append(event)
            if verbose:
                print(
                    f"[inbox-run] agent[{agent_idx}] rate-limited; advancing to next agent",
                    file=sys.stderr,
                )
            agent_idx += 1
            # Retry same item with the next agent — do NOT increment items_processed.
            continue

        if rc != 0:
            failures.append({
                "attempt": items_attempted,
                "agent_index": agent_idx,
                "agent_cli": agent.cli,
                "returncode": rc,
                "stderr_excerpt": (err or out)[-1000:],
            })
            return LoopReport(
                result=LoopResult.AGENT_FAILURE,
                items_processed=items_processed,
                items_attempted=items_attempted,
                agent_index_used_last=agent_idx,
                failures=failures,
                rate_limit_events=rate_limit_events,
                total_usage=cumulative_usage,
                items_detail=items_detail,
            )

        # Success.
        items_processed += 1
        cumulative_usage = cumulative_usage + item_usage

        # Token summary.
        if not item_usage.is_empty():
            print(
                f"  ✓  tokens: in={item_usage.input_tokens:,}  "
                f"out={item_usage.output_tokens:,}  "
                f"cache={item_usage.cache_read_tokens:,}  "
                f"cost=${item_usage.cost_usd:.4f}",
                file=sys.stderr,
            )
            print(
                f"  ∑  cumulative: in={cumulative_usage.input_tokens:,}  "
                f"out={cumulative_usage.output_tokens:,}  "
                f"cost=${cumulative_usage.cost_usd:.4f}",
                file=sys.stderr,
            )
        elif agent.cli == "opencode":
            print(
                "  (token usage not captured for opencode)",
                file=sys.stderr,
            )

        # Capture per-item structured report from agent output (claude only —
        # opencode stdout is inherited and not captured, so `out` is "").
        item_report = _extract_json_report(out)
        detail: dict[str, Any] = {
            "source_id": next_source.id,
            "connector": next_source.connector,
        }
        if item_report:
            for key in (
                "domain", "pages_created", "pages_modified",
                "decisions_captured", "contradictions", "follow_up_questions",
            ):
                if key in item_report:
                    detail[key] = item_report[key]
        items_detail.append(detail)

        # Sanity: if the inbox count didn't drop, the agent didn't move the
        # item to processed (it disobeyed the prompt or hit a silent error).
        # Treat as failure to avoid an infinite loop.
        new_pending = _count_inbox(paths)
        if new_pending >= pending:
            failures.append({
                "attempt": items_attempted,
                "agent_index": agent_idx,
                "agent_cli": agent.cli,
                "returncode": rc,
                "reason": (
                    "Agent exited 0 but inbox count did not decrease "
                    f"(before={pending}, after={new_pending}). "
                    "Likely the agent skipped mark-processed."
                ),
                "stderr_excerpt": (err or out)[-1000:],
            })
            return LoopReport(
                result=LoopResult.AGENT_FAILURE,
                items_processed=items_processed - 1,  # roll back the count we incremented
                items_attempted=items_attempted,
                agent_index_used_last=agent_idx,
                failures=failures,
                rate_limit_events=rate_limit_events,
                total_usage=cumulative_usage,
                items_detail=items_detail,
            )

        if delay_seconds > 0:
            time.sleep(delay_seconds)
