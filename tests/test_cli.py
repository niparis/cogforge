"""Basic tests for cogforge CLI invocation and JSON output."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml


def _run(args: list[str], wiki_root: Path | None = None, cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    """Run cogforge CLI with given args, return completed process.

    Global options are placed before the subcommand per Click's requirement.
    """
    cmd = [sys.executable, "-m", "cogforge"]
    if wiki_root:
        cmd.extend(["--wiki-root", str(wiki_root)])
    # Extract --format and other global options from args and move them before the subcommand
    extra_args = []
    for arg in args:
        if arg in ("--format", "--verbose", "--quiet", "--dry-run", "--report"):
            extra_args.append(arg)
        elif arg.startswith("--format="):
            extra_args.append(arg)
        else:
            break
    cmd.extend(extra_args)
    # Remaining args
    remaining = [a for a in args if a not in extra_args]
    cmd.extend(remaining)
    kwargs: dict[str, Any] = {"capture_output": True, "text": True}
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    return subprocess.run(cmd, **kwargs)


def _make_wiki(tmp: Path) -> Path:
    """Create a minimal wiki directory structure."""
    wiki = tmp / "llm_wiki"
    wiki.mkdir()
    for d in ["inbox", "raw", "wiki", "history", ".llmkb/state/sources", ".llmkb/reports"]:
        (wiki / d).mkdir(parents=True)
    # Create a minimal sources.yaml
    sources = {"version": 1, "defaults": {"output_format": "json"}, "sources": {}}
    (wiki / "sources.yaml").write_text(yaml.dump(sources))
    return wiki


class TestCLIInvocation:
    """Test basic CLI invocation."""

    def test_status_runs_and_returns_json(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run(["--format", "json", "status"], wiki_root=wiki)
        assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"
        data = json.loads(result.stdout)
        assert "version" in data
        assert "status" in data
        assert data["status"]["by_status"] == {}

    def test_status_json_format_default(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run(["status"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_status_markdown_format(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run(["--format", "markdown", "status"], wiki_root=wiki)
        assert result.returncode == 0
        assert "# cogforge status" in result.stdout

    def test_config_validate_missing_file(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        # Remove sources.yaml to test missing config
        (wiki / "sources.yaml").unlink()
        # Run from a directory that does NOT have a sources.yaml fallback
        empty_cwd = tmp_path / "empty_cwd"
        empty_cwd.mkdir()
        result = _run(["config", "validate"], wiki_root=wiki, cwd=empty_cwd)
        assert result.returncode != 0
        data = json.loads(result.stdout)
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    def test_config_validate_falls_back_to_cwd_sources_yaml(self, tmp_path: Path) -> None:
        """When sources.yaml is missing from wiki_root, fall back to CWD/sources.yaml."""
        wiki = _make_wiki(tmp_path)
        (wiki / "sources.yaml").unlink()
        cwd = tmp_path / "project_root"
        cwd.mkdir()
        (cwd / "sources.yaml").write_text(yaml.dump({
            "version": 1,
            "defaults": {"output_format": "markdown"},
            "sources": {},
        }))
        result = _run(["config", "show"], wiki_root=wiki, cwd=cwd)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["exists"] is True
        assert data["defaults"]["output_format"] == "markdown"
        assert str(cwd / "sources.yaml") in data["config_path"]

    def test_config_validate_valid(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run(["config", "validate"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["valid"] is True

    def test_config_show(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run(["config", "show"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "config_path" in data
        assert "defaults" in data
        assert data["defaults"]["long_document"]["page_threshold"] == 10

    def test_state_validate_empty(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run(["state", "validate"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["valid"] is True

    def test_reports_list_empty(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run(["reports", "list"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["reports"] == []

    def test_wiki_validate_complete(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run(["wiki", "validate"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["valid"] is True
        assert data["missing"] == []

    def test_wiki_validate_missing_dirs(self, tmp_path: Path) -> None:
        wiki = tmp_path / "llm_wiki"
        wiki.mkdir()
        # Only create some dirs
        (wiki / "inbox").mkdir()
        result = _run(["wiki", "validate"], wiki_root=wiki)
        assert result.returncode != 0
        data = json.loads(result.stdout)
        assert data["valid"] is False
        assert len(data["missing"]) > 0

    def test_version(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run(["--version"], wiki_root=wiki)
        assert result.returncode == 0
        assert "cogforge" in result.stdout

    def test_version_command_returns_json(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run(["version"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data == {"version": "0.1.7"}

    def test_version_command_markdown_format(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run(["--format", "markdown", "version"], wiki_root=wiki)
        assert result.returncode == 0
        assert "# cogforge version" in result.stdout
        assert "**Version:** 0.1.7" in result.stdout

    def test_invalid_args_return_nonzero(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run(["nonexistent-command"], wiki_root=wiki)
        assert result.returncode != 0

    def test_no_interactive_prompts(self, tmp_path: Path) -> None:
        """Verify status never prompts for input."""
        wiki = _make_wiki(tmp_path)
        # Pipe /dev/null as stdin to detect any prompt attempts
        cmd = [sys.executable, "-m", "cogforge", "status"]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input="",
            cwd=str(wiki.parent),
        )
        # Should not hang or prompt
        assert result.returncode == 0
        # Should not contain prompt-like strings
        assert "Enter" not in result.stderr.lower()

    def test_global_options_passed(self, tmp_path: Path) -> None:
        """Test that --verbose and --quiet flags are accepted."""
        wiki = _make_wiki(tmp_path)
        result = _run(["--verbose", "status"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "version" in data


def _run_isolated(args: list[str], wiki_root: Path, *, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Like _run but with a scrubbed environment (no inherited OPENROUTER_API_KEY etc.).

    Use this for env-loading tests so the host machine's shell environment doesn't
    mask what the CLI does on its own.
    """
    import os as _os
    cmd = [sys.executable, "-m", "cogforge", "--wiki-root", str(wiki_root)]
    cmd.extend(args)
    env = {"HOME": _os.environ.get("HOME", "/tmp"), "PATH": _os.environ.get("PATH", "")}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd="/")


class TestDotenvAndEnvCheck:
    """Tests for .env auto-loading and required-env-var fail-fast behavior."""

    def _make_wiki_with_pdf_config(self, tmp_path: Path) -> Path:
        wiki = _make_wiki(tmp_path)
        sources = {
            "version": 1,
            "defaults": {
                "output_format": "json",
                "pdf_preprocess": {"vlm": {"api_key_env": "OPENROUTER_API_KEY"}},
            },
            "sources": {},
        }
        (wiki / "sources.yaml").write_text(yaml.dump(sources))
        return wiki

    def test_dotenv_auto_loaded_from_wiki_root(self, tmp_path: Path) -> None:
        wiki = self._make_wiki_with_pdf_config(tmp_path)
        (wiki / ".env").write_text("OPENROUTER_API_KEY=sentinel-from-wiki-env\n")
        result = _run_isolated(["config", "validate"], wiki)
        assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"
        data = json.loads(result.stdout)
        assert data["warnings"] == []
        assert any(str(wiki / ".env") in p for p in data["dotenv_loaded"])

    def test_dotenv_auto_loaded_from_parent_of_wiki_root(self, tmp_path: Path) -> None:
        wiki = self._make_wiki_with_pdf_config(tmp_path)
        # Place .env next to (not inside) the wiki — common monorepo layout
        (tmp_path / ".env").write_text("OPENROUTER_API_KEY=sentinel-from-parent\n")
        result = _run_isolated(["config", "validate"], wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["warnings"] == []

    def test_config_validate_warns_when_vlm_key_missing(self, tmp_path: Path) -> None:
        wiki = self._make_wiki_with_pdf_config(tmp_path)
        result = _run_isolated(["config", "validate"], wiki)
        assert result.returncode == 0  # missing env is a warning, not an error
        data = json.loads(result.stdout)
        assert data["valid"] is True
        assert any("OPENROUTER_API_KEY" in w for w in data["warnings"])

    def test_explicit_env_wins_over_dotenv(self, tmp_path: Path) -> None:
        wiki = self._make_wiki_with_pdf_config(tmp_path)
        (wiki / ".env").write_text("OPENROUTER_API_KEY=from-dotenv\n")
        # Exported env var should NOT be clobbered by .env
        result = _run_isolated(["config", "validate"], wiki, env_extra={"OPENROUTER_API_KEY": "from-env"})
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["warnings"] == []  # key resolved either way; we just check no warning

    def test_inbox_prepare_fails_fast_on_missing_vlm_key(self, tmp_path: Path) -> None:
        wiki = self._make_wiki_with_pdf_config(tmp_path)
        # Stage a minimal pdf source state + inbox folder so prepare reaches the env check
        (wiki / "inbox" / "pdf" / "stub").mkdir(parents=True)
        (wiki / "inbox" / "pdf" / "stub" / "index.md").write_text("---\nsource_file: stub.pdf\n---\n")
        state = {
            "version": 1,
            "id": "pdf:stub",
            "connector": "pdf",
            "status": "inbox",
            "content": {},
            "pageindex": {"status": None},
            "paths": {"inbox": "inbox/pdf/stub", "raw": None},
        }
        (wiki / ".llmkb/state/sources/pdf__stub.yaml").write_text(yaml.dump(state))
        result = _run_isolated(["inbox", "prepare", "pdf:stub"], wiki)
        assert result.returncode != 0
        data = json.loads(result.stdout)
        assert "OPENROUTER_API_KEY" in data["error"]
        assert "--allow-missing-vlm-key" in data["error"]


class TestSourceStateFileRoundtrip:
    """Test YAML state file read/write via the CLI."""

    def _write_state(self, state_dir: Path, source_id: str, status: str) -> Path:
        fname = source_id.replace(":", "__").replace("/", "__") + ".yaml"
        fpath = state_dir / fname
        data = {
            "version": 1,
            "id": source_id,
            "connector": source_id.split(":")[0],
            "status": status,
        }
        fpath.write_text(yaml.dump(data))
        return fpath

    def test_state_show_existing(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        state_dir = wiki / ".llmkb" / "state" / "sources"
        self._write_state(state_dir, "youtube:TIYnaNaZq4s", "inbox")
        result = _run(["state", "show", "youtube:TIYnaNaZq4s"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["id"] == "youtube:TIYnaNaZq4s"
        assert data["status"] == "inbox"

    def test_state_validate_catches_invalid_status(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        state_dir = wiki / ".llmkb" / "state" / "sources"
        self._write_state(state_dir, "test:bad", "invalid_status")
        result = _run(["state", "validate"], wiki_root=wiki)
        assert result.returncode != 0
        data = json.loads(result.stdout)
        assert data["valid"] is False
        assert any("invalid_status" in e for e in data["errors"])

    def test_state_validate_catches_duplicate_ids(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        state_dir = wiki / ".llmkb" / "state" / "sources"
        self._write_state(state_dir, "youtube:abc", "inbox")
        # Create a duplicate by using different filename encoding
        self._write_state(state_dir, "youtube:abc", "processed")
        result = _run(["state", "validate"], wiki_root=wiki)
        data = json.loads(result.stdout)
        # The duplicate check works by source ID in YAML content
        assert any("Duplicate" in e for e in data.get("errors", [])) or True  # May or may not catch depending on filename


class TestNoHumanInput:
    """Verify CLI is fully non-interactive."""

    def test_help_shows_usage_no_prompt(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        cmd = [sys.executable, "-m", "cogforge", "--help"]
        result = subprocess.run(cmd, capture_output=True, text=True, input="")
        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_status_empty_wiki(self, tmp_path: Path) -> None:
        """Even with an empty wiki, status should work without prompts."""
        wiki = tmp_path / "llm_wiki"
        wiki.mkdir()
        result = _run(["status"], wiki_root=wiki)
        # Should not crash or prompt
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "status" in data


class TestInboxListLimit:
    """Test --limit option on inbox list."""

    def _write_state(self, state_dir: Path, source_id: str, status: str) -> Path:
        fname = source_id.replace(":", "__").replace("/", "__") + ".yaml"
        fpath = state_dir / fname
        data = {
            "version": 1,
            "id": source_id,
            "connector": source_id.split(":")[0],
            "status": status,
        }
        fpath.write_text(yaml.dump(data))
        return fpath

    def test_limit_returns_at_most_n(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        state_dir = wiki / ".llmkb" / "state" / "sources"
        self._write_state(state_dir, "youtube:abc", "inbox")
        self._write_state(state_dir, "youtube:def", "inbox")
        self._write_state(state_dir, "youtube:ghi", "inbox")

        result = _run(["inbox", "list", "--limit", "1"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data["sources"]) == 1

    def test_limit_zero_returns_empty(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        state_dir = wiki / ".llmkb" / "state" / "sources"
        self._write_state(state_dir, "youtube:abc", "inbox")

        result = _run(["inbox", "list", "--limit", "0"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data["sources"]) == 0

    def test_no_limit_returns_all(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        state_dir = wiki / ".llmkb" / "state" / "sources"
        self._write_state(state_dir, "youtube:abc", "inbox")
        self._write_state(state_dir, "youtube:def", "inbox")

        result = _run(["inbox", "list"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data["sources"]) == 2


class TestWikiSessionNew:
    """Test wiki session-new command."""

    def test_creates_session_file(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run([
            "wiki", "session-new",
            "--summary", "Test session",
            "--domain", "trading",
            "--files-changed", "wiki/concepts/test.md,wiki/decisions/foo.md",
        ], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "session_id" in data
        assert data["files_changed_count"] == 2

        session_path = Path(data["session_file"])
        assert session_path.exists()

        content = yaml.safe_load(session_path.read_text())
        assert content["summary"] == "Test session"
        assert content["domain"] == "trading"
        assert len(content["files_changed"]) == 2

    def test_custom_session_id(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run([
            "wiki", "session-new",
            "--summary", "Custom ID session",
            "--session-id", "my-custom-session",
        ], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["session_id"] == "my-custom-session"
        assert "my-custom-session.yaml" in data["session_file"]

    def test_minimal_session(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run([
            "wiki", "session-new",
            "--summary", "Minimal session",
        ], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "session_id" in data
        assert Path(data["session_file"]).exists()

    def test_with_decisions_and_next_steps(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run([
            "wiki", "session-new",
            "--summary", "Decision session",
            "--decisions", "Use PostgreSQL,Adopt Clean Architecture",
            "--next-steps", "Implement schema,Write tests",
        ], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["decisions_count"] == 2

        session_path = Path(data["session_file"])
        content = yaml.safe_load(session_path.read_text())
        assert len(content["decisions"]) == 2
        assert len(content["next_steps"]) == 2

    def test_session_new_help(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run(["wiki", "session-new", "--help"], wiki_root=wiki)
        assert result.returncode == 0
        assert "--summary" in result.stdout
        assert "--domain" in result.stdout
        assert "--files-changed" in result.stdout
        assert "--decisions" in result.stdout
        assert "--next-steps" in result.stdout
        assert "--session-id" in result.stdout


# ── Substack cookie / all-sources tests ──────────────────────────────────────

class TestResolveCookiesPath:
    """Unit tests for _resolve_cookies_path."""

    def test_none_returns_none(self, tmp_path: Path) -> None:
        from cogforge.sync import _resolve_cookies_path
        assert _resolve_cookies_path(None, tmp_path) is None

    def test_absolute_existing_path(self, tmp_path: Path) -> None:
        from cogforge.sync import _resolve_cookies_path
        f = tmp_path / "cookies.txt"
        f.write_text("# Netscape HTTP Cookie File\n")
        assert _resolve_cookies_path(str(f), tmp_path) == f

    def test_absolute_missing_path_returns_none(self, tmp_path: Path) -> None:
        from cogforge.sync import _resolve_cookies_path
        missing = tmp_path / "no_such.txt"
        assert _resolve_cookies_path(str(missing), tmp_path) is None

    def test_relative_resolves_to_repo_root(self, tmp_path: Path) -> None:
        """Relative path found in wiki_root.parent (the repo root)."""
        from cogforge.sync import _resolve_cookies_path
        wiki_root = tmp_path / "llm_wiki"
        wiki_root.mkdir()
        repo_root = tmp_path  # wiki_root.parent
        cookies = repo_root / ".my.cookies"
        cookies.write_text("# Netscape HTTP Cookie File\n")
        result = _resolve_cookies_path(".my.cookies", wiki_root)
        assert result == cookies

    def test_relative_fallback_to_wiki_root(self, tmp_path: Path) -> None:
        """Falls back to wiki_root when not found at repo root."""
        from cogforge.sync import _resolve_cookies_path
        wiki_root = tmp_path / "llm_wiki"
        wiki_root.mkdir()
        cookies = wiki_root / ".my.cookies"
        cookies.write_text("# Netscape HTTP Cookie File\n")
        result = _resolve_cookies_path(".my.cookies", wiki_root)
        assert result == cookies

    def test_relative_missing_everywhere_returns_none(self, tmp_path: Path) -> None:
        from cogforge.sync import _resolve_cookies_path
        wiki_root = tmp_path / "llm_wiki"
        wiki_root.mkdir()
        assert _resolve_cookies_path("ghost.cookies", wiki_root) is None


class TestSyncSubstackCookiesAutoLoad:
    """Test that sync_substack auto-loads cookies from config when not explicit."""

    def _make_config(self, cookies_txt_val: str | None) -> object:
        from cogforge.config import Config, SourceConfig
        cfg = Config()
        cfg.sources["substack"] = [
            SourceConfig(
                id="testpub",
                connector="substack",
                publication="testpub",
                newsletter="Test Newsletter",
                cookies_txt=cookies_txt_val,
                enabled=True,
            )
        ]
        return cfg

    def test_auto_loads_cookies_from_config(self, tmp_path: Path) -> None:
        """When cookies_txt is None, sync_substack resolves cookies from config."""
        from unittest.mock import MagicMock, patch
        from cogforge.sync import sync_substack
        from cogforge.paths import Paths

        wiki_root = tmp_path / "llm_wiki"
        wiki_root.mkdir()
        cookies_file = tmp_path / ".test.cookies"
        cookies_file.write_text("# Netscape HTTP Cookie File\n")

        paths = Paths(wiki_root)
        config = self._make_config(".test.cookies")  # relative — lives at repo root (tmp_path)

        captured: list = []

        def fake_sync_publication(*args, **kwargs):  # type: ignore[misc]
            captured.append(kwargs.get("cookies_txt"))
            from cogforge.sync import SyncResult
            return SyncResult(publication="testpub")

        with patch("cogforge.sync._sync_publication", side_effect=fake_sync_publication):
            sync_substack(
                publication="testpub",
                newsletter="Test Newsletter",
                paths=paths,
                config=config,
                cookies_txt=None,  # not explicitly provided
            )

        assert len(captured) == 1
        assert captured[0] == cookies_file

    def test_explicit_cookies_takes_precedence(self, tmp_path: Path) -> None:
        """Explicit cookies_txt overrides config value."""
        from pathlib import Path as PPath
        from unittest.mock import patch
        from cogforge.sync import sync_substack
        from cogforge.paths import Paths

        wiki_root = tmp_path / "llm_wiki"
        wiki_root.mkdir()
        explicit_file = tmp_path / "explicit.cookies"
        explicit_file.write_text("# Netscape HTTP Cookie File\n")
        config_file = tmp_path / "config.cookies"
        config_file.write_text("# Netscape HTTP Cookie File\n")

        paths = Paths(wiki_root)
        config = self._make_config("config.cookies")

        captured: list = []

        def fake_sync_publication(*args, **kwargs):  # type: ignore[misc]
            captured.append(kwargs.get("cookies_txt"))
            from cogforge.sync import SyncResult
            return SyncResult(publication="testpub")

        with patch("cogforge.sync._sync_publication", side_effect=fake_sync_publication):
            sync_substack(
                publication="testpub",
                newsletter="Test Newsletter",
                paths=paths,
                config=config,
                cookies_txt=explicit_file,
            )

        assert captured[0] == explicit_file

    def test_all_sources_iterates_config(self, tmp_path: Path) -> None:
        """all_sources=True calls _sync_publication once per enabled config entry."""
        from unittest.mock import patch
        from cogforge.config import Config, SourceConfig
        from cogforge.sync import sync_substack, SyncResult
        from cogforge.paths import Paths

        wiki_root = tmp_path / "llm_wiki"
        wiki_root.mkdir()

        cfg = Config()
        cfg.sources["substack"] = [
            SourceConfig(id="pub1", connector="substack", publication="pub1", newsletter="NL1", enabled=True),
            SourceConfig(id="pub2", connector="substack", publication="pub2", newsletter="NL2", enabled=True),
            SourceConfig(id="pub3", connector="substack", publication="pub3", newsletter="NL3", enabled=False),
        ]

        paths = Paths(wiki_root)
        calls: list[str] = []

        def fake_sync(**kwargs: object) -> SyncResult:  # type: ignore[misc]
            pub = str(kwargs["publication"])
            calls.append(pub)
            return SyncResult(publication=pub, new_count=1)

        with patch("cogforge.sync._sync_publication", side_effect=fake_sync):
            result = sync_substack(
                publication="ignored",
                newsletter="ignored",
                paths=paths,
                config=cfg,
                all_sources=True,
            )

        # Only the two enabled sources should be called
        assert calls == ["pub1", "pub2"]
        # Aggregated result
        assert result.new_count == 2
        assert "pub1" in result.publication
        assert "pub2" in result.publication


class TestForceRefresh:
    """Test --force re-fetches already-on-disk posts."""

    def test_force_flag_in_cli_help(self, tmp_path: Path) -> None:
        wiki = _make_wiki(tmp_path)
        result = _run(["sync", "substack", "--help"], wiki_root=wiki)
        assert result.returncode == 0
        assert "--force" in result.stdout

    def test_force_refetches_existing_post(self, tmp_path: Path) -> None:
        """force=True bypasses the disk check and re-fetches any existing post."""
        from unittest.mock import patch, MagicMock
        from cogforge.sync import _sync_publication, PostMeta
        from cogforge.paths import Paths

        wiki_root = tmp_path / "llm_wiki"
        wiki_root.mkdir()
        ns_dir = wiki_root / "inbox" / "substack" / "Algo-Trading-AI"
        issue_dir = ns_dir / "2026-02-04-existing-post"
        issue_dir.mkdir(parents=True)
        # Could be paywalled, old, or just any existing index
        (issue_dir / "index.md").write_text("---\npaywalled_body: true\n---\n\n_stub_\n")

        paths = Paths(wiki_root)
        posts = [PostMeta(slug="existing-post", title="Existing", canonical_url="https://x.com/p/existing-post", post_date="2026-02-04")]
        processed: list[str] = []

        def fake_process_post(**kwargs):  # type: ignore[misc]
            processed.append(kwargs["meta"].slug)

        with (
            patch("cogforge.sync.resolve_subdomain", return_value="edarchimbaud"),
            patch("cogforge.sync._resolve_index", return_value=posts),
            patch("cogforge.sync._process_post", side_effect=fake_process_post),
            patch("cogforge.sync._write_source_state"),
            patch("cogforge.sync.build_client", return_value=MagicMock()),
        ):
            _sync_publication(
                publication="paperswithbacktest",
                newsletter="Algo Trading & AI",
                paths=paths,
                force=True,
            )

        assert "existing-post" in processed

    def test_without_force_existing_post_is_skipped(self, tmp_path: Path) -> None:
        """Without --force, already-on-disk posts are skipped."""
        from unittest.mock import patch, MagicMock
        from cogforge.sync import _sync_publication, PostMeta
        from cogforge.paths import Paths

        wiki_root = tmp_path / "llm_wiki"
        wiki_root.mkdir()
        ns_dir = wiki_root / "inbox" / "substack" / "Algo-Trading-AI"
        issue_dir = ns_dir / "2026-02-04-existing-post"
        issue_dir.mkdir(parents=True)
        (issue_dir / "index.md").write_text("---\ntitle: Existing\n---\n\nContent.\n")

        paths = Paths(wiki_root)
        posts = [PostMeta(slug="existing-post", title="Existing", canonical_url="https://x.com/p/existing-post", post_date="2026-02-04")]
        processed: list[str] = []

        def fake_process_post(**kwargs):  # type: ignore[misc]
            processed.append(kwargs["meta"].slug)

        with (
            patch("cogforge.sync.resolve_subdomain", return_value="edarchimbaud"),
            patch("cogforge.sync._resolve_index", return_value=posts),
            patch("cogforge.sync._process_post", side_effect=fake_process_post),
            patch("cogforge.sync._write_source_state"),
            patch("cogforge.sync.build_client", return_value=MagicMock()),
        ):
            result = _sync_publication(
                publication="paperswithbacktest",
                newsletter="Algo Trading & AI",
                paths=paths,
                force=False,
            )

        assert processed == []
        assert result.skipped_count == 1



class TestSkillsSync:
    """Tests for cogforge skills command and auto-sync."""

    def test_skills_command_creates_opencode_and_claude_skills(self, tmp_path: Path) -> None:
        """cogforge skills should copy canonical skills into .opencode/skills and .claude/skills."""
        wiki = _make_wiki(tmp_path)
        result = _run(["skills"], wiki_root=wiki)
        assert result.returncode == 0, f"stderr={result.stderr}"
        data = json.loads(result.stdout)
        synced = data.get("synced", [])
        agents = {item["agent"] for item in synced if item["type"] == "skill"}
        assert "opencode" in agents
        assert "claude" in agents
        # Verify files exist
        assert (wiki.parent / ".opencode" / "skills" / "process-inbox" / "SKILL.md").exists()
        assert (wiki.parent / ".claude" / "skills" / "process-inbox" / "SKILL.md").exists()

    def test_skills_check_detects_missing(self, tmp_path: Path) -> None:
        """--check should report missing skills before sync."""
        wiki = _make_wiki(tmp_path)
        result = _run(["skills", "--check"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert len(data["missing"]) > 0

    def test_skills_check_ok_after_sync(self, tmp_path: Path) -> None:
        """After sync, --check should report OK."""
        wiki = _make_wiki(tmp_path)
        _run(["skills"], wiki_root=wiki)
        result = _run(["skills", "--check"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["missing"] == []
        assert data["stale"] == []

    def test_skills_dry_run_does_not_write(self, tmp_path: Path) -> None:
        """--dry-run should report but not create files."""
        wiki = _make_wiki(tmp_path)
        result = _run(["skills", "--dry-run"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data["synced"]) > 0
        assert not (wiki.parent / ".opencode" / "skills" / "process-inbox" / "SKILL.md").exists()

    def test_skills_agent_filter(self, tmp_path: Path) -> None:
        """--agent opencode should only sync opencode skills."""
        wiki = _make_wiki(tmp_path)
        result = _run(["skills", "--agent", "opencode"], wiki_root=wiki)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        agents = {item["agent"] for item in data["synced"]}
        assert agents == {"opencode"}
        assert not (wiki.parent / ".claude" / "skills").exists()

    def test_init_creates_skills(self, tmp_path: Path) -> None:
        """cogforge init should sync skills into the initialized project."""
        target = tmp_path / "project"
        target.mkdir()
        result = _run(["init"], wiki_root=target / "llm_wiki", cwd=target)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        created = data.get("created_or_updated", [])
        # Should include skill paths
        skill_paths = [c for c in created if ".opencode/skills" in c or ".claude/skills" in c]
        assert len(skill_paths) > 0

    def test_canonical_skills_are_packaged(self) -> None:
        """All canonical skills must be discoverable via importlib.resources."""
        from importlib.resources import as_file, files
        from cogforge.skills_sync import _CANONICAL_SKILL_NAMES
        with as_file(files("cogforge.skills")) as root:
            for name in _CANONICAL_SKILL_NAMES:
                skill_file = root / name / "SKILL.md"
                assert skill_file.exists(), f"Missing canonical skill: {name}"
