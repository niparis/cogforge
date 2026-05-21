"""Tests for `cogforge inbox run` and the inbox_runner module.

The agent CLI (claude/opencode) is faked with a small shell script controlled
by FAKE_AGENT_BEHAVIOR env var. This lets us exercise the success / rate-limit
/ failure code paths without spawning a real LLM session.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from cogforge.config import AgentConfig
from cogforge.inbox_runner import (
    DEFAULT_RATE_LIMIT_PATTERNS,
    LoopResult,
    _build_command,
    _detect_rate_limit,
    run_loop,
)
from cogforge.paths import Paths
from cogforge.state import (
    ContentInfo,
    Origin,
    SourcePaths,
    SourceState,
    SourceStatus,
    save_state,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


def _make_wiki(tmp: Path) -> Path:
    """Create a minimal wiki directory structure (mirrors tests/test_cli.py)."""
    wiki = tmp / "llm_wiki"
    wiki.mkdir()
    for d in ["inbox", "raw", "wiki", "history", ".llmkb/state/sources", ".llmkb/reports"]:
        (wiki / d).mkdir(parents=True)
    return wiki


def _seed_inbox(wiki: Path, ids: list[str], connector: str = "test") -> None:
    """Create N inbox state files with status='inbox'."""
    state_dir = wiki / ".llmkb" / "state" / "sources"
    for sid in ids:
        state = SourceState(
            id=sid,
            connector=connector,
            status=SourceStatus.INBOX.value,
            origin=Origin(url=f"https://example.com/{sid}", title=sid),
            content=ContentInfo(estimated_chars=1000),
            paths=SourcePaths(inbox=f"inbox/{connector}/{sid}"),
        )
        save_state(state_dir, state)


def _write_sources_yaml(wiki: Path, agents: list[dict]) -> None:
    """Write a sources.yaml with the given agents block."""
    (wiki / "sources.yaml").write_text(yaml.dump({
        "version": 1,
        "defaults": {"output_format": "json"},
        "agents": agents,
        "sources": {},
    }))


def _make_fake_agent(
    bin_dir: Path,
    name: str,
    *,
    behavior: str,
    wiki_root: Path,
) -> Path:
    """Write a fake agent stub script.

    Behaviors:
      success     — flip the next inbox state file to processed, exit 0
      rate_limit  — print rate_limit_error to stderr, exit 1
      fail        — print generic error to stderr, exit 1
      noop_zero   — exit 0 without touching state (tests the "no progress" guard)
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / name
    state_dir = wiki_root / ".llmkb" / "state" / "sources"

    if behavior == "success":
        # Use Python so we don't depend on yq/jq being installed. We pick the
        # first INBOX state file and rewrite its status to processed.
        body = textwrap.dedent(f"""\
            #!/usr/bin/env bash
            exec "{sys.executable}" - <<'PYEOF'
            import sys, glob, os, re
            state_dir = "{state_dir}"
            for path in sorted(glob.glob(os.path.join(state_dir, "*.yaml"))):
                txt = open(path).read()
                if re.search(r"^status: inbox\\b", txt, re.MULTILINE):
                    new = re.sub(r"^status: inbox\\b", "status: processed", txt, count=1, flags=re.MULTILINE)
                    open(path, "w").write(new)
                    sys.exit(0)
            sys.exit(0)
            PYEOF
        """)
    elif behavior == "rate_limit":
        body = textwrap.dedent("""\
            #!/usr/bin/env bash
            echo "Error: rate_limit_error (status 429)" >&2
            exit 1
        """)
    elif behavior == "fail":
        body = textwrap.dedent("""\
            #!/usr/bin/env bash
            echo "Error: something went terribly wrong" >&2
            exit 1
        """)
    elif behavior == "noop_zero":
        body = textwrap.dedent("""\
            #!/usr/bin/env bash
            echo "I did nothing" >&2
            exit 0
        """)
    else:
        raise ValueError(f"Unknown behavior: {behavior}")

    stub.write_text(body)
    stub.chmod(0o755)
    return stub


@pytest.fixture
def fake_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Prepend a fake bin dir to PATH so subprocess can find our stubs."""
    bin_dir = tmp_path / "fake_bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir


# ── unit tests: _detect_rate_limit ───────────────────────────────────────────


class TestDetectRateLimit:
    def test_zero_returncode_is_never_rate_limit(self):
        agent = AgentConfig(cli="claude")
        assert _detect_rate_limit(agent, 0, "rate_limit_error everywhere", "") is False

    def test_claude_default_pattern_matches(self):
        agent = AgentConfig(cli="claude")
        assert _detect_rate_limit(agent, 1, "", "Error: rate_limit_error") is True

    def test_claude_overloaded_matches(self):
        agent = AgentConfig(cli="claude")
        assert _detect_rate_limit(agent, 1, "", "529 overloaded_error") is True

    def test_opencode_default_pattern_matches(self):
        agent = AgentConfig(cli="opencode")
        assert _detect_rate_limit(agent, 1, "", "Rate Limit exceeded") is True

    def test_non_matching_failure_is_not_rate_limit(self):
        agent = AgentConfig(cli="claude")
        assert _detect_rate_limit(agent, 1, "", "syntax error in prompt") is False

    def test_custom_patterns_override_defaults(self):
        agent = AgentConfig(cli="claude", rate_limit_patterns=["my_custom_signal"])
        # default pattern should NOT match because we overrode
        assert _detect_rate_limit(agent, 1, "", "rate_limit_error") is False
        assert _detect_rate_limit(agent, 1, "", "my_custom_signal here") is True

    def test_empty_pattern_list_never_matches(self):
        agent = AgentConfig(cli="claude", rate_limit_patterns=[])
        assert _detect_rate_limit(agent, 1, "", "rate_limit_error") is False

    def test_case_insensitive(self):
        agent = AgentConfig(cli="claude")
        assert _detect_rate_limit(agent, 1, "", "RATE_LIMIT_ERROR") is True


# ── unit tests: _build_command ──────────────────────────────────────────────


class TestBuildCommand:
    def test_claude_minimal(self):
        cmd = _build_command(AgentConfig(cli="claude"))
        assert cmd[0] == "claude"
        assert "--dangerously-skip-permissions" in cmd
        assert "--print" in cmd
        # Default prompt is empty; callers inject per-item prompt via PROMPT_TEMPLATE.
        assert cmd[-1] == ""

    def test_claude_with_explicit_prompt(self):
        prompt = "Process inbox source foo (bar) at path baz using the /process-inbox skill."
        cmd = _build_command(AgentConfig(cli="claude"), prompt=prompt)
        assert cmd[-1] == prompt

    def test_claude_with_model(self):
        cmd = _build_command(AgentConfig(cli="claude", model="claude-opus-4-5"))
        assert "--model" in cmd
        assert "claude-opus-4-5" in cmd

    def test_opencode_minimal(self):
        cmd = _build_command(AgentConfig(cli="opencode"))
        assert cmd[0] == "opencode"
        assert cmd[1] == "run"
        # Default prompt is empty string; callers inject per-item prompt.
        assert cmd[-1] == ""

    def test_extra_args_passed_through(self):
        cmd = _build_command(AgentConfig(cli="claude", extra_args=["--effort", "high"]))
        assert "--effort" in cmd
        assert "high" in cmd

    def test_unknown_cli_raises(self):
        with pytest.raises(ValueError):
            _build_command(AgentConfig(cli="nope"))


# ── integration: run_loop with fake agents ──────────────────────────────────


class TestRunLoop:
    def test_no_agents_returns_no_agents(self, tmp_path: Path):
        wiki = _make_wiki(tmp_path)
        report = run_loop(Paths(wiki), agents=[])
        assert report.result == LoopResult.NO_AGENTS

    def test_dry_run_does_not_invoke(self, tmp_path: Path, fake_path: Path):
        wiki = _make_wiki(tmp_path)
        _seed_inbox(wiki, ["src-1", "src-2"])
        # Fake agent that would fail if called — proves dry-run skips invocation
        _make_fake_agent(fake_path, "claude", behavior="fail", wiki_root=wiki)

        report = run_loop(
            Paths(wiki),
            agents=[AgentConfig(cli="claude")],
            dry_run=True,
        )
        assert report.result == LoopResult.DRY_RUN
        assert report.pending_count == 2
        assert report.planned_command is not None
        assert report.planned_command[0] == "claude"

    def test_empty_inbox_returns_inbox_empty(self, tmp_path: Path, fake_path: Path):
        wiki = _make_wiki(tmp_path)
        _make_fake_agent(fake_path, "claude", behavior="fail", wiki_root=wiki)

        report = run_loop(Paths(wiki), agents=[AgentConfig(cli="claude")])
        assert report.result == LoopResult.INBOX_EMPTY
        assert report.items_processed == 0
        assert report.items_attempted == 0

    def test_drain_inbox(self, tmp_path: Path, fake_path: Path):
        wiki = _make_wiki(tmp_path)
        _seed_inbox(wiki, ["src-1", "src-2", "src-3"])
        _make_fake_agent(fake_path, "claude", behavior="success", wiki_root=wiki)

        report = run_loop(
            Paths(wiki),
            agents=[AgentConfig(cli="claude", timeout_seconds=10)],
            delay_seconds=0,
        )
        assert report.result == LoopResult.SUCCESS
        assert report.items_processed == 3
        assert report.failures == []

    def test_falls_back_on_rate_limit(self, tmp_path: Path, fake_path: Path):
        """agent[0] always rate-limits; agent[1] (different binary name) succeeds."""
        wiki = _make_wiki(tmp_path)
        _seed_inbox(wiki, ["src-1", "src-2"])
        _make_fake_agent(fake_path, "claude", behavior="rate_limit", wiki_root=wiki)
        _make_fake_agent(fake_path, "opencode", behavior="success", wiki_root=wiki)

        report = run_loop(
            Paths(wiki),
            agents=[
                AgentConfig(cli="claude", timeout_seconds=10),
                AgentConfig(cli="opencode", timeout_seconds=10),
            ],
            delay_seconds=0,
        )
        assert report.result == LoopResult.SUCCESS
        assert report.items_processed == 2
        # agent[0] was rate-limited at least once before we advanced
        assert len(report.rate_limit_events) >= 1
        assert report.rate_limit_events[0]["agent_index"] == 0
        assert report.agent_index_used_last == 1

    def test_stops_on_non_rate_limit_failure(self, tmp_path: Path, fake_path: Path):
        wiki = _make_wiki(tmp_path)
        _seed_inbox(wiki, ["src-1", "src-2"])
        _make_fake_agent(fake_path, "claude", behavior="fail", wiki_root=wiki)

        report = run_loop(
            Paths(wiki),
            agents=[AgentConfig(cli="claude", timeout_seconds=10)],
            delay_seconds=0,
        )
        assert report.result == LoopResult.AGENT_FAILURE
        assert report.items_processed == 0
        assert len(report.failures) == 1
        assert report.failures[0]["agent_cli"] == "claude"

    def test_all_agents_rate_limited(self, tmp_path: Path, fake_path: Path):
        wiki = _make_wiki(tmp_path)
        _seed_inbox(wiki, ["src-1"])
        _make_fake_agent(fake_path, "claude", behavior="rate_limit", wiki_root=wiki)
        _make_fake_agent(fake_path, "opencode", behavior="rate_limit", wiki_root=wiki)

        report = run_loop(
            Paths(wiki),
            agents=[
                AgentConfig(cli="claude", timeout_seconds=10),
                AgentConfig(cli="opencode", timeout_seconds=10),
            ],
            delay_seconds=0,
        )
        assert report.result == LoopResult.ALL_RATE_LIMITED
        assert report.items_processed == 0
        assert len(report.rate_limit_events) == 2

    def test_max_items_honored(self, tmp_path: Path, fake_path: Path):
        wiki = _make_wiki(tmp_path)
        _seed_inbox(wiki, ["src-1", "src-2", "src-3", "src-4", "src-5"])
        _make_fake_agent(fake_path, "claude", behavior="success", wiki_root=wiki)

        report = run_loop(
            Paths(wiki),
            agents=[AgentConfig(cli="claude", timeout_seconds=10)],
            max_items=2,
            delay_seconds=0,
        )
        assert report.result == LoopResult.MAX_ITEMS_REACHED
        assert report.items_processed == 2

    def test_noop_zero_treated_as_failure(self, tmp_path: Path, fake_path: Path):
        """Agent exits 0 but doesn't touch state → guard kicks in to avoid infinite loop."""
        wiki = _make_wiki(tmp_path)
        _seed_inbox(wiki, ["src-1"])
        _make_fake_agent(fake_path, "claude", behavior="noop_zero", wiki_root=wiki)

        report = run_loop(
            Paths(wiki),
            agents=[AgentConfig(cli="claude", timeout_seconds=10)],
            delay_seconds=0,
        )
        assert report.result == LoopResult.AGENT_FAILURE
        assert any("did not decrease" in (f.get("reason") or "") for f in report.failures)


# ── integration: full CLI via subprocess ─────────────────────────────────────


def _run_cli(args: list[str], wiki: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "cogforge", "--wiki-root", str(wiki)]
    # Global flags must come before subcommand
    extra: list[str] = []
    rest: list[str] = []
    for a in args:
        if a in ("--dry-run", "--verbose", "--quiet") or a.startswith("--format"):
            extra.append(a)
        else:
            rest.append(a)
    cmd.extend(extra)
    cmd.extend(rest)
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


class TestCLIInboxRun:
    def test_no_agents_configured_errors(self, tmp_path: Path):
        wiki = _make_wiki(tmp_path)
        (wiki / "sources.yaml").write_text(yaml.dump({"version": 1, "sources": {}}))
        result = _run_cli(["inbox", "run"], wiki)
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert "agents" in data["error"].lower()

    def test_dry_run_with_agents_succeeds(self, tmp_path: Path):
        wiki = _make_wiki(tmp_path)
        _write_sources_yaml(wiki, [{"cli": "claude", "model": "claude-opus-4-5"}])
        result = _run_cli(["--dry-run", "inbox", "run"], wiki)
        assert result.returncode == 0, f"stderr={result.stderr}"
        data = json.loads(result.stdout)
        assert data["result"] == "dry_run"
        assert data["planned_command"][0] == "claude"

    def test_empty_inbox_exits_zero(self, tmp_path: Path):
        wiki = _make_wiki(tmp_path)
        _write_sources_yaml(wiki, [{"cli": "claude"}])
        # No inbox state files → empty
        result = _run_cli(["inbox", "run"], wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["result"] == "inbox_empty"

    def test_drain_via_cli(self, tmp_path: Path, fake_path: Path):
        wiki = _make_wiki(tmp_path)
        _seed_inbox(wiki, ["src-a", "src-b"])
        _write_sources_yaml(wiki, [{"cli": "claude", "timeout_seconds": 10}])
        _make_fake_agent(fake_path, "claude", behavior="success", wiki_root=wiki)

        env = {"PATH": f"{fake_path}{os.pathsep}{os.environ['PATH']}"}
        result = _run_cli(["inbox", "run", "--delay", "0"], wiki, extra_env=env)
        assert result.returncode == 0, f"stderr={result.stderr} stdout={result.stdout}"
        data = json.loads(result.stdout)
        assert data["result"] == "success"
        assert data["items_processed"] == 2

    def test_all_rate_limited_exits_3(self, tmp_path: Path, fake_path: Path):
        wiki = _make_wiki(tmp_path)
        _seed_inbox(wiki, ["src-x"])
        _write_sources_yaml(wiki, [
            {"cli": "claude", "timeout_seconds": 10},
            {"cli": "opencode", "timeout_seconds": 10},
        ])
        _make_fake_agent(fake_path, "claude", behavior="rate_limit", wiki_root=wiki)
        _make_fake_agent(fake_path, "opencode", behavior="rate_limit", wiki_root=wiki)

        env = {"PATH": f"{fake_path}{os.pathsep}{os.environ['PATH']}"}
        result = _run_cli(["inbox", "run", "--delay", "0"], wiki, extra_env=env)
        # ExitCode.PARTIAL_SUCCESS == 3
        assert result.returncode == 3, f"stderr={result.stderr}"
        data = json.loads(result.stdout)
        assert data["result"] == "all_rate_limited"


# ── unit: defaults are present for known CLIs ───────────────────────────────


def test_default_rate_limit_patterns_cover_known_clis():
    assert "claude" in DEFAULT_RATE_LIMIT_PATTERNS
    assert "opencode" in DEFAULT_RATE_LIMIT_PATTERNS
    assert all(DEFAULT_RATE_LIMIT_PATTERNS[c] for c in ("claude", "opencode"))
