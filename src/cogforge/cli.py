
"""cogforge CLI entry point.

Agent-facing command-line interface for maintaining the LLM wiki.
Uses Click for nested command groups with JSON default output.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

import click
import yaml
from loguru import logger

from cogforge import __version__
from cogforge.config import AgentConfig, Config, SourceConfig, default_config, load_config, validate_config
from cogforge.inbox_runner import LoopResult, run_loop
from cogforge.pageindexing import detect_long_document, run_pageindex, PageIndexResult
from cogforge.paths import Paths, _encode_source_id, _decode_source_id, resolve_wiki_root
from cogforge.reports import Report, render_json, render_markdown, load_report, save_report
from cogforge.sync import SyncResult, sync_substack
from cogforge.sync_apple_notes import sync_apple_notes, AppleNotesSyncResult
from cogforge.skills_sync import sync_skills, check_skills, _is_cogforge_repo
from cogforge.sync_youtube import sync_youtube, YouTubeSyncResult
from cogforge.prepare import PrepareResult, prepare_inbox_source
from cogforge.state import (
    SourceState, SourceStatus, encode_source_id, decode_source_id,
    list_source_states, load_state, save_state, validate_state,
)


class ExitCode:
    SUCCESS = 0
    COMMAND_ERROR = 1
    VALIDATION_FAILED = 2
    PARTIAL_SUCCESS = 3


def _log_result(cmd_name: str, result: dict[str, Any], duration_ms: int) -> None:
    """Log a structured JSON result line to the configured loguru file sink."""
    logger.info(json.dumps({
        "command": cmd_name,
        "result": result,
        "duration_ms": duration_ms,
    }))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _echo_json(data: dict[str, Any]) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False))


def fail(message: str, exit_code: int = ExitCode.COMMAND_ERROR) -> None:
    _echo_json({"error": message, "exit_code": exit_code})
    sys.exit(exit_code)


def _get_ctx(ctx: click.Context) -> dict[str, Any]:
    """Build CLIContext dict from Click params stored by CogforgeGroup."""
    return ctx.obj or {}


def _load_dotenv_files(wiki_root: Path) -> list[Path]:
    """Load .env from candidate locations into os.environ.

    Search order (first hit wins per variable; existing os.environ is never overwritten):
      1. <wiki_root>/.env
      2. <wiki_root>/../.env  (project root above the wiki — common layout)
      3. <CWD>/.env

    Returns the list of files actually loaded, for telemetry.
    """
    from dotenv import dotenv_values

    candidates: list[Path] = []
    seen: set[Path] = set()
    for raw in (wiki_root / ".env", wiki_root.parent / ".env", Path.cwd() / ".env"):
        try:
            resolved = raw.resolve()
        except (OSError, RuntimeError):
            continue
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        candidates.append(resolved)

    loaded: list[Path] = []
    for path in candidates:
        values = dotenv_values(path)
        applied = False
        for key, value in values.items():
            if value is None:
                continue
            # Strip `export ` prefix that some shells write (dotenv_values already does,
            # but be defensive against future format changes).
            if os.environ.get(key):
                continue
            os.environ[key] = value
            applied = True
        if applied:
            loaded.append(path)
    return loaded


def _check_required_env(config) -> list[dict[str, str]]:
    """Return a list of missing-env-var problems, keyed by the config field that references them.

    Currently checks: pdf_preprocess.vlm.api_key_env.
    Each entry: {"field": "...", "env_var": "...", "hint": "..."}
    """
    problems: list[dict[str, str]] = []
    pdf_cfg = config.pdf_preprocess
    key_name = pdf_cfg.vlm_api_key_env
    if key_name and not os.environ.get(key_name):
        problems.append({
            "field": "defaults.pdf_preprocess.vlm.api_key_env",
            "env_var": key_name,
            "hint": (
                f"{key_name} is not set in the environment. "
                f"Add it to <wiki_root>/.env or the parent project's .env, "
                f"or export it before running cogforge. "
                f"Without it, PDF visual summaries will silently fail."
            ),
        })
    return problems


# ── Custom Click group that resolves global options early ────────────────────

class CogforgeGroup(click.Group):
    # Global flags that should be accepted before or after the subcommand
    _GLOBAL_FLAGS = frozenset({
        "--verbose", "--quiet", "--dry-run",
        "--format", "--wiki-root", "--config", "--report",
    })

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """Store resolved global options on the context before parsing.

        Pulls known global flags to the front of the arg list so they are
        accepted regardless of position (before or after the subcommand).
        """
        # Pull global flags to the front
        front: list[str] = []
        rest: list[str] = []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg in self._GLOBAL_FLAGS:
                front.append(arg)
                if arg in ("--format", "--wiki-root", "--config", "--report"):
                    if i + 1 < len(args) and not args[i + 1].startswith("-"):
                        front.append(args[i + 1])
                        i += 1
            elif arg.startswith("--format=") or arg.startswith("--wiki-root=") or arg.startswith("--config=") or arg.startswith("--report="):
                front.append(arg)
            else:
                rest.append(arg)
            i += 1

        new_args = front + rest if front else args
        remaining = super().parse_args(ctx, new_args)

        params = ctx.params or {}
        raw_root = params.get("wiki_root") or ""
        wiki_root = resolve_wiki_root(Path(raw_root) if raw_root else None)
        config_path = Path(params["config"]) if params.get("config") else None

        # Load .env files BEFORE config so any env-interpolated values are available.
        # Anything already in os.environ wins.
        dotenv_files = _load_dotenv_files(wiki_root)

        resolved_config_path: Path | None = None
        if config_path:
            resolved_config_path = config_path
            config = load_config(config_path)
        else:
            default_path = wiki_root / "sources.yaml"
            if default_path.is_file():
                resolved_config_path = default_path
                config = load_config(default_path)
            else:
                cwd_path = Path.cwd() / "sources.yaml"
                if cwd_path.is_file():
                    resolved_config_path = cwd_path
                    config = load_config(cwd_path)
                else:
                    config = default_config()

        paths = Paths(wiki_root)

        verbose = params.get("verbose", False)
        quiet = params.get("quiet", False)

        # Configure loguru: verbose → DEBUG, quiet → ERROR only, default → INFO
        logger.remove()
        level = "ERROR" if quiet else ("DEBUG" if verbose else "INFO")
        logger.add(sys.stderr, level=level, format="{level}  {name}  {message}")

        ctx.ensure_object(dict)
        ctx.obj["cli_ctx"] = {
            "wiki_root": wiki_root,
            "config": config,
            "config_path": str(resolved_config_path) if resolved_config_path else None,
            "paths": paths,
            "output_format": params.get("format", "json"),
            "report_path": Path(params["report"]) if params.get("report") else None,
            "dry_run": params.get("dry_run", False),
            "verbose": verbose,
            "quiet": quiet,
            "dotenv_files": [str(p) for p in dotenv_files],
        }
        if dotenv_files:
            logger.debug(f"Loaded .env from: {', '.join(str(p) for p in dotenv_files)}")

        # Auto-sync skills if inside a Cogforge-managed repo
        _maybe_sync_skills(wiki_root, quiet, verbose)

        return remaining


def _maybe_sync_skills(wiki_root: Path, quiet: bool, verbose: bool) -> None:
    """Silently sync canonical skills into the local agent directories."""
    # Skills live at the project root, not inside llm_wiki
    project_root = wiki_root.parent
    if not _is_cogforge_repo(project_root):
        return
    # Avoid syncing on commands that handle it explicitly
    import sys
    args = sys.argv[1:]
    if not args:
        return
    # Skip auto-sync for init and skills commands (accounting for global flags before subcommand)
    subcommands = {"init", "skills"}
    if any(arg in subcommands for arg in args):
        return
    try:
        result = sync_skills(wiki_root, dry_run=False)
        if verbose and result.get("synced"):
            for item in result["synced"]:
                logger.debug(f"synced {item['type']} {item['name']} → {item['dst']}")
    except Exception:
        # Never fail the main command because of skill sync issues
        if verbose:
            logger.debug("Skill sync failed (non-critical)")


def _cli_ctx(ctx: click.Context) -> dict[str, Any]:
    return ctx.obj.get("cli_ctx", {})


# ── Global options decorator ────────────────────────────────────────────────

def global_options(func: click.Command) -> click.Command:
    func = click.option("--wiki-root", type=click.Path(), default=None)(func)
    func = click.option("--config", type=click.Path(), default=None)(func)
    func = click.option("--format", type=click.Choice(["json", "markdown"]), default="json")(func)
    func = click.option("--report", type=click.Path(), default=None)(func)
    func = click.option("--dry-run", is_flag=True, default=False)(func)
    func = click.option("--verbose", is_flag=True, default=False)(func)
    func = click.option("--quiet", is_flag=True, default=False)(func)
    return func


# ── Root command ─────────────────────────────────────────────────────────────

@click.group(cls=CogforgeGroup, context_settings={
    "help_option_names": ["-h", "--help"],
    "ignore_unknown_options": True,
})
@global_options
@click.version_option(version=__version__, prog_name="cogforge")
def main(**kwargs) -> None:
    """cogforge - agent-facing CLI for the LLM wiki."""


# ── version ─────────────────────────────────────────────────────────────────

@main.command("version")
@click.pass_context
def version_command(ctx: click.Context) -> None:
    """Show the cogforge package version."""
    c = _cli_ctx(ctx)
    output_format = c.get("output_format", "json")
    if output_format == "markdown":
        click.echo(f"# cogforge version\n\n**Version:** {__version__}")
    else:
        _echo_json({"version": __version__})


# ── init ────────────────────────────────────────────────────────────────────

def _copy_template_contents(src: Path, dst: Path, force: bool) -> list[str]:
    copied: list[str] = []
    for item in sorted(src.rglob("*")):
        rel = item.relative_to(src)
        if rel.name == "__init__.py":
            continue
        if any(part == "__pycache__" for part in rel.parts):
            continue
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if target.exists() and not force:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        copied.append(str(rel))
    return copied


def _detect_installed_clis() -> list[str]:
    """Return a list of installed agent CLI names ('claude', 'opencode')."""
    found: list[str] = []
    for name in ("claude", "opencode"):
        if shutil.which(name):
            found.append(name)
    return found


def _write_sources_yaml_with_agents(project_root: Path, installed_clis: list[str]) -> None:
    """Patch the copied sources.yaml to include a detected agents block."""
    cfg_path = project_root / "sources.yaml"
    if not cfg_path.is_file():
        return

    data: dict[str, Any] = yaml.safe_load(cfg_path.read_text()) or {}

    # Only inject if the agents list is empty (user hasn't customised yet)
    if data.get("agents"):
        return

    agents: list[dict[str, Any]] = []
    for cli in installed_clis:
        entry: dict[str, Any] = {"cli": cli}
        # Sensible defaults per CLI
        if cli == "claude":
            entry["timeout_seconds"] = 1800
        elif cli == "opencode":
            entry["rate_limit_patterns"] = ["rate_limit_error", "529", "Overloaded"]
        agents.append(entry)

    if agents:
        data["agents"] = agents
        cfg_path.write_text(yaml.dump(data, sort_keys=False, allow_unicode=True))


def _ensure_wiki_indexes(wiki_root: Path, force: bool) -> list[str]:
    index_specs = {
        "concepts/concepts_index.md": "# Concepts Index\n",
        "domain-context/domain-context_index.md": "# Domain Context Index\n",
        "decisions/decisions_index.md": "# Decisions Index\n",
        "synthesis/synthesis_index.md": "# Synthesis Index\n",
        "derived-outputs/derived-outputs_index.md": "# Derived Outputs Index\n",
    }
    created: list[str] = []
    for rel, content in index_specs.items():
        path = wiki_root / "wiki" / rel
        if path.exists() and not force:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        created.append(str(path.relative_to(wiki_root.parent)))
    return created


@main.command("init")
@click.argument("target", type=click.Path(path_type=Path), default=Path("."), required=False)
@click.option("--force", is_flag=True, default=False, help="Overwrite existing scaffold files.")
@click.pass_context
def init_cmd(ctx: click.Context, target: Path, force: bool) -> None:
    """Initialize a Cogforge knowledge-base repository."""
    c = _cli_ctx(ctx)
    output_format = c["output_format"]
    project_root = target.resolve()
    wiki_root = project_root / "llm_wiki"

    with as_file(files("cogforge.templates.kb")) as template_root:
        copied = _copy_template_contents(template_root, project_root, force)

    installed_clis = _detect_installed_clis()
    if installed_clis:
        _write_sources_yaml_with_agents(project_root, installed_clis)

    paths = Paths(wiki_root)
    paths.ensure()
    for rel in [
        "wiki/concepts",
        "wiki/domain-context",
        "wiki/decisions",
        "wiki/synthesis",
        "wiki/derived-outputs",
    ]:
        (wiki_root / rel).mkdir(parents=True, exist_ok=True)
    indexes = _ensure_wiki_indexes(wiki_root, force)

    # Sync skills for all supported agents on init
    try:
        skill_result = sync_skills(project_root, agents=["opencode", "claude"], dry_run=False)
        skill_synced = [item["dst"] for item in skill_result.get("synced", [])]
    except Exception:
        skill_synced = []

    result = {
        "project_root": str(project_root),
        "wiki_root": str(wiki_root),
        "created_or_updated": copied + indexes + skill_synced,
        "force": force,
    }
    if output_format == "markdown":
        lines = [
            "# cogforge init",
            "",
            f"**Project root:** `{project_root}`",
            f"**Wiki root:** `{wiki_root}`",
            "",
            "## Created or updated",
        ]
        lines.extend(f"- {item}" for item in result["created_or_updated"])
        click.echo("\n".join(lines))
    else:
        _echo_json(result)


# ── status ──────────────────────────────────────────────────────────────────

@main.command("status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """Show pipeline status."""
    c = _cli_ctx(ctx)
    wiki_root = c["wiki_root"]
    output_format = c["output_format"]

    if not wiki_root.is_dir():
        fail(f"Wiki root not found: {wiki_root}")

    status_counts: dict[str, int] = {}
    connector_counts: dict[str, int] = {}
    failed_sources: list[str] = []
    inbox_sources: list[str] = []
    pageindex_pending = 0
    pageindex_failed = 0

    state_dir = c["paths"].state_sources
    if state_dir.is_dir():
        for state_file in sorted(state_dir.glob("*.yaml")):
            try:
                state = load_state(state_dir, decode_source_id(state_file.stem))
            except Exception:
                failed_sources.append(state_file.stem)
                status_counts["failed"] = status_counts.get("failed", 0) + 1
                continue
            if state is None or not state.id:
                failed_sources.append(state_file.stem)
                continue
            status_counts[state.status] = status_counts.get(state.status, 0) + 1
            connector_counts[state.connector] = connector_counts.get(state.connector, 0) + 1
            if state.status == SourceStatus.FAILED.value:
                failed_sources.append(state.id)
            elif state.status == SourceStatus.INBOX.value:
                inbox_sources.append(state.id)
            if state.pageindex.status == "pending":
                pageindex_pending += 1
            elif state.pageindex.status == "failed":
                pageindex_failed += 1

    inbox_dir = c["paths"].inbox
    if inbox_dir.is_dir():
        for connector_dir in inbox_dir.iterdir():
            if connector_dir.is_dir() and not connector_dir.name.startswith("."):
                connector_counts.setdefault(connector_dir.name, 0)
                for item in connector_dir.iterdir():
                    if item.is_file() and item.suffix in (".md", ".txt", ".html"):
                        connector_counts[connector_dir.name] += 1

    reports_dir = c["paths"].reports
    recent_reports: list[str] = []
    if reports_dir.is_dir():
        recent_reports = sorted((f.name for f in reports_dir.glob("*.yaml")), reverse=True)[:5]

    result: dict[str, Any] = {
        "version": __version__,
        "wiki_root": str(wiki_root),
        "status": {
            "by_status": status_counts,
            "by_connector": connector_counts,
            "failed_sources": failed_sources,
            "inbox_count": len(inbox_sources),
            "pageindex_pending": pageindex_pending,
            "pageindex_failed": pageindex_failed,
        },
    }
    if recent_reports:
        result["recent_reports"] = recent_reports

    if output_format == "markdown":
        lines = [f"# cogforge status", "", f"**Version:** {__version__}",
                 f"**Wiki root:** `{wiki_root}`", "", "## Sources by status"]
        for st, count in sorted(status_counts.items()):
            lines.append(f"- {st}: {count}")
        lines.append("")
        lines.append("## Sources by connector")
        for conn, count in sorted(connector_counts.items()):
            lines.append(f"- {conn}: {count}")
        if failed_sources:
            lines.append("")
            lines.append("## Failed sources")
            for fs in failed_sources:
                lines.append(f"- {fs}")
        if inbox_sources:
            lines.append("")
            lines.append(f"## Inbox ({len(inbox_sources)} sources)")
            for src in inbox_sources[:20]:
                lines.append(f"- {src}")
            if len(inbox_sources) > 20:
                lines.append(f"- ... and {len(inbox_sources) - 20} more")
        click.echo("\n".join(lines))
    else:
        _echo_json(result)


# ── config ──────────────────────────────────────────────────────────────────

@main.group("config")
@click.pass_context
def config_group(ctx: click.Context) -> None:
    """Manage configuration."""


@config_group.command("validate")
@click.pass_context
def config_validate(ctx: click.Context) -> None:
    """Validate sources.yaml configuration."""
    import time
    start_time = time.time()
    import time
    start_time = time.time()
    c = _cli_ctx(ctx)
    config = c["config"]
    paths = c["paths"]
    output_format = c["output_format"]
    resolved_cfg_path = Path(c["config_path"]) if c.get("config_path") else paths.root / "sources.yaml"

    errors = validate_config(config, resolved_cfg_path)
    if not resolved_cfg_path.is_file():
        errors.append(f"Config file not found: {resolved_cfg_path}")

    # Surface missing env vars as warnings so the user can see them at a glance
    # without breaking offline workflows that legitimately don't need them.
    warnings: list[str] = []
    for problem in _check_required_env(config):
        warnings.append(f"{problem['field']}: {problem['hint']}")

    result = {
        "config_path": str(resolved_cfg_path),
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "dotenv_loaded": c.get("dotenv_files", []),
        "source_count": sum(len(v) for v in config.sources.values()),
    }

    if output_format == "markdown":
        lines = ["# Config Validation"]
        if result["valid"]:
            lines.append("Configuration is valid.")
        else:
            lines.append(f"Found {len(errors)} error(s):")
            for e in errors:
                lines.append(f"- {e}")
        if warnings:
            lines.append("")
            lines.append(f"## Warnings ({len(warnings)})")
            for w in warnings:
                lines.append(f"- {w}")
        if result["dotenv_loaded"]:
            lines.append("")
            lines.append("## Loaded .env files")
            for p in result["dotenv_loaded"]:
                lines.append(f"- `{p}`")
        click.echo("\n".join(lines))
    else:
        _echo_json(result)

    if errors:
        sys.exit(ExitCode.VALIDATION_FAILED)


@config_group.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Show resolved configuration with defaults applied."""
    c = _cli_ctx(ctx)
    cfg = c["config"]
    output_format = c["output_format"]
    resolved_cfg_path = Path(c["config_path"]) if c.get("config_path") else c["paths"].root / "sources.yaml"

    result = {
        "config_path": str(resolved_cfg_path),
        "exists": resolved_cfg_path.is_file(),
        "version": cfg.version,
        "defaults": {
            "output_format": cfg.output_format,
            "long_document": {
                "page_threshold": cfg.long_document.page_threshold,
                "char_threshold": cfg.long_document.char_threshold,
            },
        },
        "sources": {
            conn: [
                {k: v for k, v in {
                    "id": s.id, "enabled": s.enabled,
                    "cookies_txt": s.cookies_txt, "language_preferences": s.language_preferences,
                    "root_title": s.root_title, "max_depth": s.max_depth,
                    "newsletter": s.newsletter, "publication": s.publication,
                    "playlist_id": s.playlist_id,
                }.items() if v is not None}
                for s in srcs
            ]
            for conn, srcs in cfg.sources.items()
        },
    }

    if output_format == "markdown":
        lines = ["# Resolved Configuration", ""]
        lines.append(f"- **Source count:** {sum(len(v) for v in cfg.sources.values())}")
        lines.append(f"- **Default format:** {cfg.output_format}")
        lines.append(f"- **Page threshold:** {cfg.long_document.page_threshold}")
        lines.append(f"- **Char threshold:** {cfg.long_document.char_threshold}")
        for conn, srcs in sorted(cfg.sources.items()):
            lines.append(f"- {conn}: {len(srcs)} source(s)")
        click.echo("\n".join(lines))
    else:
        _echo_json(result)


# ── state ───────────────────────────────────────────────────────────────────

@main.group("state")
@click.pass_context
def state_group(ctx: click.Context) -> None:
    """Inspect source state files."""


@state_group.command("show")
@click.argument("source_id", required=False)
@click.pass_context
def state_show(ctx: click.Context, source_id: str | None) -> None:
    """Show source state for a given source ID."""
    c = _cli_ctx(ctx)
    state_dir = c["paths"].state_sources

    if not state_dir.is_dir():
        fail("No state directory found")

    if source_id is None:
        sources = sorted(s.stem for s in state_dir.glob("*.yaml"))
        _echo_json({"sources": sources, "count": len(sources)})
        return

    state = load_state(state_dir, source_id)
    if state is None:
        fail(f"State file not found for source: {source_id}")

    if c["output_format"] == "markdown":
        lines = [f"# State: {state.id}", ""]
        for key in ["connector", "document_type", "status"]:
            val = getattr(state, key, None)
            if val:
                lines.append(f"- **{key}:** {val}")
        if state.origin.url:
            lines.append(f"- **url:** {state.origin.url}")
        if state.origin.title:
            lines.append(f"- **title:** {state.origin.title}")
        if state.content.sha256:
            lines.append(f"- **sha256:** {state.content.sha256[:16]}...")
        if state.content.estimated_chars:
            lines.append(f"- **estimated_chars:** {state.content.estimated_chars}")
        click.echo("\n".join(lines))
    else:
        _echo_json(state.to_dict())


@state_group.command("validate")
@click.pass_context
def state_validate(ctx: click.Context) -> None:
    """Validate all source state files for consistency."""
    c = _cli_ctx(ctx)
    result = validate_state(c["paths"].state_sources)

    if c["output_format"] == "markdown":
        lines = ["# State Validation"]
        if result["errors"]:
            lines.append(f"Found {len(result['errors'])} error(s):")
            for e in result["errors"]:
                lines.append(f"- {e}")
        else:
            lines.append(f"All {result['sources_checked']} source(s) are valid.")
        if result["warnings"]:
            lines.append(f"\n{len(result['warnings'])} warning(s):")
            for w in result["warnings"]:
                lines.append(f"- {w}")
        click.echo("\n".join(lines))
    else:
        _echo_json(result)

    if result["errors"]:
        sys.exit(ExitCode.VALIDATION_FAILED)


@state_group.command("repair")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be repaired without making changes")
@click.pass_context
def state_repair(ctx: click.Context, dry_run: bool) -> None:
    """Repair safe state drift.

    Safe repairs include:
    - Recomputing missing content hashes from source files
    - Restoring missing report references
    - Marking missing package paths as validation errors
    """
    c = _cli_ctx(ctx)
    state_dir = c["paths"].state_sources
    output_format = c["output_format"]

    if not state_dir.is_dir():
        fail("No state directory found")

    repairs: list[str] = []
    errors: list[str] = []
    sources_checked = 0

    for state_file in sorted(state_dir.glob("*.yaml")):
        try:
            state = load_state(state_dir, decode_source_id(state_file.stem))
        except Exception as e:
            errors.append(f"{state_file.name}: parse error - {e}")
            continue

        if state is None or not state.id:
            errors.append(f"{state_file.name}: failed to parse or missing id")
            continue

        sources_checked += 1
        file_changed = False

        # Repair: ensure state has an ID matching the file
        if not state.id:
            state.id = decode_source_id(state_file.stem)
            repairs.append(f"{state.id}: restored missing id from filename")
            file_changed = True

        if state.status == SourceStatus.PROCESSED.value and not state.paths.raw:
            repairs.append(f"{state.id}: warning - processed status but no raw path")

        if state.status == SourceStatus.FAILED.value and not state.last_error.message:
            repairs.append(f"{state.id}: warning - failed status but no error message")

        if file_changed and not dry_run:
            save_state(state_dir, state)

    result = {
        "repaired": len(repairs),
        "errors": errors,
        "sources_checked": sources_checked,
        "dry_run": dry_run,
        "details": repairs,
    }

    if output_format == "markdown":
        lines = ["# State Repair"]
        if dry_run:
            lines.append("**Mode:** dry run (no changes made)")
        lines.append(f"\n**Sources checked:** {sources_checked}")
        lines.append(f"**Repairs found:** {len(repairs)}")
        if repairs:
            lines.append("")
            lines.append("## Repairs")
            for r in repairs:
                lines.append(f"- {r}")
        if errors:
            lines.append("")
            lines.append("## Errors")
            for e in errors:
                lines.append(f"- {e}")
        if not repairs and not errors:
            lines.append("\nNo repairs needed.")
        click.echo("\n".join(lines))
    else:
        _echo_json(result)


# ── reports ─────────────────────────────────────────────────────────────────

@main.group("reports")
@click.pass_context
def reports_group(ctx: click.Context) -> None:
    """Manage run reports."""


@reports_group.command("list")
@click.pass_context
def reports_list(ctx: click.Context) -> None:
    """List recent run reports."""
    c = _cli_ctx(ctx)
    reports_dir = c["paths"].reports
    reports = []
    if reports_dir.is_dir():
        reports = sorted((f.name for f in reports_dir.glob("*.yaml")), reverse=True)
    _echo_json({"reports": reports, "count": len(reports)})


@reports_group.command("show")
@click.argument("run_id")
@click.pass_context
def reports_show(ctx: click.Context, run_id: str) -> None:
    """Show a stored report by run ID."""
    c = _cli_ctx(ctx)
    report = load_report(c["paths"].reports, run_id)
    if report is None:
        fail(f"Report not found: {run_id}")

    if c["output_format"] == "markdown":
        click.echo(render_markdown(report))
    else:
        _echo_json(report.to_dict())


@reports_group.command("render")
@click.argument("path", type=click.Path(exists=True))
@click.pass_context
def reports_render(ctx: click.Context, path: Path) -> None:
    """Render a stored YAML report to JSON or Markdown."""
    c = _cli_ctx(ctx)
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        fail(f"Invalid report file: {path}")
    report = Report.from_dict(data)

    if c["output_format"] == "markdown":
        click.echo(render_markdown(report))
    else:
        _echo_json(report.to_dict())


# ── sync ──────────────────────────────────────────────────────────────────────

@main.group("sync")
@click.pass_context
def sync_group(ctx: click.Context) -> None:
    """Synchronize external sources into the wiki inbox."""


@sync_group.command("substack")
@click.option("--publication", default="paperswithbacktest", help="Substack publication name (subdomain)")
@click.option("--newsletter", default="Algo Trading & AI", help="Display newsletter name")
@click.option("--source-id", default=None, help="Sync only one source by slug")
@click.option("--all-sources", is_flag=True, default=False, help="Sync all configured Substack sources")
@click.option("--max", type=int, default=None, help="Stop after N new posts")
@click.option("--refresh-index", is_flag=True, default=False, help="Rebuild post discovery index")
@click.option("--cookies-txt", type=click.Path(), default=None, help="Netscape cookies.txt for auth")
@click.option("--skip-pdfs", is_flag=True, default=False, help="Skip PDF download")
@click.option("--force", is_flag=True, default=False, help="Re-fetch posts that are already on disk")
@click.pass_context
def sync_substack_cmd(
    ctx: click.Context,
    publication: str,
    newsletter: str,
    source_id: str | None,
    all_sources: bool,
    max: int | None,
    refresh_index: bool,
    cookies_txt: Path | None,
    skip_pdfs: bool,
    force: bool,
) -> None:
    """Sync a Substack publication into the wiki inbox."""
    c = _cli_ctx(ctx)
    paths = c["paths"]
    config = c["config"]
    dry_run = c["dry_run"]
    verbose = c["verbose"]

    if source_id and all_sources:
        fail("Cannot use --source-id and --all-sources together")

    result = sync_substack(
        publication=publication,
        newsletter=newsletter,
        paths=paths,
        config=config,
        source_id=source_id,
        all_sources=all_sources,
        max_posts=max,
        refresh_index=refresh_index,
        cookies_txt=Path(cookies_txt) if cookies_txt else None,
        skip_pdfs=skip_pdfs,
        force=force,
        dry_run=dry_run,
        verbose=verbose,
    )

    if c["output_format"] == "markdown":
        lines = [
            f"# Substack Sync: {publication}",
            f"**Discovered:** {result.total_discovered}",
            f"**New:** {result.new_count}",
            f"**Skipped:** {result.skipped_count}",
            f"**Errors:** {result.error_count}",
        ]
        if result.source_ids:
            lines.append("")
            lines.append("## Synced Sources")
            for sid in result.source_ids:
                lines.append(f"- {sid}")
        if result.errors:
            lines.append("")
            lines.append("## Errors")
            for e in result.errors:
                lines.append(f"- {e}")
        click.echo("\n".join(lines))
    else:
        _echo_json({
            "publication": result.publication,
            "connector": result.connector,
            "total_discovered": result.total_discovered,
            "new_count": result.new_count,
            "skipped_count": result.skipped_count,
            "error_count": result.error_count,
            "source_ids": result.source_ids,
            "errors": result.errors,
        })

    if result.error_count > 0:
        sys.exit(ExitCode.PARTIAL_SUCCESS)


@sync_group.command("youtube")
@click.option("--source-id", default=None, help="Sync one configured YouTube source")
@click.option("--all", "all_sources", is_flag=True, default=False, help="Sync all enabled YouTube sources")
@click.option("--url", default=None, help="Fetch a single video URL outside playlist config")
@click.option("--video-id", default=None, help="Fetch a single video ID")
@click.option("--max", type=int, default=None, help="Stop after N new transcripts")
@click.option("--include-failed", is_flag=True, default=False, help="Retry previously failed items")
@click.pass_context
def sync_youtube_cmd(
    ctx: click.Context,
    source_id: str | None,
    all_sources: bool,
    url: str | None,
    video_id: str | None,
    max: int | None,
    include_failed: bool,
) -> None:
    """Sync YouTube videos and transcripts into the wiki inbox."""
    c = _cli_ctx(ctx)
    paths = c["paths"]
    config = c["config"]
    dry_run = c["dry_run"]
    verbose = c["verbose"]

    result = sync_youtube(
        source_id=source_id,
        all_sources=all_sources,
        config=config,
        paths=paths,
        url=url,
        video_id=video_id,
        max_videos=max,
        include_failed=include_failed,
        dry_run=dry_run,
        verbose=verbose,
    )

    if c["output_format"] == "markdown":
        lines = [
            f"# YouTube Sync",
            f"**Discovered:** {result.total_discovered}",
            f"**New:** {result.new_count}",
            f"**Skipped:** {result.skipped_count}",
            f"**Errors:** {result.error_count}",
        ]
        if result.source_ids:
            lines.append("")
            lines.append("## Synced Sources")
            for sid in result.source_ids:
                lines.append(f"- {sid}")
        if result.errors:
            lines.append("")
            lines.append("## Errors")
            for e in result.errors:
                lines.append(f"- {e}")
        click.echo("\n".join(lines))
    else:
        _echo_json({
            "connector": result.connector,
            "total_discovered": result.total_discovered,
            "new_count": result.new_count,
            "skipped_count": result.skipped_count,
            "error_count": result.error_count,
            "source_ids": result.source_ids,
            "errors": result.errors,
        })

    if result.error_count > 0:
        sys.exit(ExitCode.PARTIAL_SUCCESS)


@sync_group.command("apple-notes")
@click.option("--source-id", default=None, help="Export one configured Apple Notes root")
@click.option("--all", "all_sources", is_flag=True, default=False, help="Export all enabled Apple Notes sources")
@click.option("--root-title", default=None, help="Override configured root note title")
@click.option("--max-depth", type=int, default=None, help="Limit graph traversal depth")
@click.pass_context
def sync_apple_notes_cmd(
    ctx: click.Context,
    source_id: str | None,
    all_sources: bool,
    root_title: str | None,
    max_depth: int | None,
) -> None:
    """Export Apple Notes from configured root notes into the wiki inbox."""
    c = _cli_ctx(ctx)
    paths = c["paths"]
    config = c["config"]
    dry_run = c["dry_run"]
    verbose = c["verbose"]

    result = sync_apple_notes(
        paths=paths,
        config=config,
        source_id=source_id,
        all_sources=all_sources,
        root_title=root_title,
        max_depth=max_depth,
        dry_run=dry_run,
        verbose=verbose,
    )

    if c["output_format"] == "markdown":
        lines = [
            f"# Apple Notes Sync",
            f"**Discovered:** {result.total_discovered}",
            f"**New:** {result.new_count}",
            f"**Skipped:** {result.skipped_count}",
            f"**Errors:** {result.error_count}",
        ]
        if result.source_ids:
            lines.append("")
            lines.append("## Exported Notes")
            for sid in result.source_ids:
                lines.append(f"- {sid}")
                if sid in result.pdfs:
                    for pdf in result.pdfs[sid]:
                        lines.append(f"  - PDF: {pdf}")
        if result.errors:
            lines.append("")
            lines.append("## Errors")
            for e in result.errors:
                lines.append(f"- {e}")
        click.echo("\n".join(lines))
    else:
        _echo_json({
            "connector": result.connector,
            "total_discovered": result.total_discovered,
            "new_count": result.new_count,
            "skipped_count": result.skipped_count,
            "error_count": result.error_count,
            "source_ids": result.source_ids,
            "pdfs": result.pdfs,
            "errors": result.errors,
        })

    if result.error_count > 0:
        sys.exit(ExitCode.PARTIAL_SUCCESS)


# ── inbox ───────────────────────────────────────────────────────────────────────

def _read_frontmatter(path: Path) -> dict:
    """Return the YAML frontmatter dict from a Markdown file, or {} if absent."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            return yaml.safe_load(text[4:end]) or {}
    return {}


@main.group("inbox")
@click.pass_context
def inbox_group(ctx: click.Context) -> None:
    """Inspect and manage sources waiting for LLM compilation."""


@inbox_group.command("list")
@click.option("--connector", default=None, help="Filter by connector name")
@click.option("--pageindex", type=click.Choice(["pending", "complete", "failed"]), default=None, help="Filter by PageIndex status")
@click.option("--failed", is_flag=True, default=False, help='Show only failed sources (shortcut for --status failed)')
@click.option(
    "--status", "status_filter",
    type=click.Choice(["inbox", "processed", "failed", "excluded", "all"]),
    default="inbox",
    show_default=True,
    help='Filter by lifecycle status. Use "all" to see every source.',
)
@click.option("--limit", type=int, default=None, help="Return at most N sources")
@click.pass_context
def inbox_list(ctx: click.Context, connector: str | None, pageindex: str | None, failed: bool, status_filter: str, limit: int | None) -> None:
    """List inbox sources (pending by default).

    Pass --status all to see sources in every lifecycle state.
    """
    c = _cli_ctx(ctx)
    output_format = c["output_format"]
    state_dir = c["paths"].state_sources

    # --failed flag takes precedence over --status
    if failed:
        effective_status: str | None = SourceStatus.FAILED.value
    elif status_filter == "all":
        effective_status = None
    else:
        effective_status = status_filter

    states = list_source_states(
        state_dir,
        status=effective_status,
        connector=connector,
        pageindex_status=pageindex,
        failed_only=False,
    )
    sources: list[dict[str, Any]] = [
        {
            "id": state.id,
            "connector": state.connector,
            "status": state.status,
            "document_type": state.document_type,
            "origin_url": state.origin.url,
            "origin_title": state.origin.title,
            "sha256": state.content.sha256,
            "estimated_chars": state.content.estimated_chars,
            "pageindex_status": state.pageindex.status,
            "pageindex_artifact": state.pageindex.artifact_path,
            "inbox_path": state.paths.inbox,
            "raw_path": state.paths.raw,
            "last_error_phase": state.last_error.phase,
            "last_error_message": state.last_error.message,
            "excluded_reason": state.excluded.reason,
            "excluded_note": state.excluded.note,
            "last_sync": state.runs.last_sync,
        }
        for state in states
    ]

    if limit is not None and limit >= 0:
        sources = sources[:limit]

    result: dict[str, Any] = {
        "sources": sources,
        "count": len(sources),
    }

    if output_format == "markdown":
        lines = ["# Inbox Sources", ""]
        if not sources:
            lines.append("No sources in inbox.")
        else:
            lines.append(f"**{len(sources)} source(s):**")
            lines.append("")
            for s in sources:
                status_icon = {"inbox": "📥", "processed": "✅", "failed": "❌", "excluded": "🚫"}.get(s["status"], "❓")
                lines.append(f"- {status_icon} `{s['id']}` — {s['connector']} — {s['status']}")
                if s["origin_title"]:
                    lines.append(f"  - {s['origin_title']}")
                if s["pageindex_status"]:
                    lines.append(f"  - pageindex: {s['pageindex_status']}")
                if s["last_error_message"]:
                    lines.append(f"  - error: {s['last_error_message']}")
        click.echo("\n".join(lines))
    else:
        _echo_json(result)


@inbox_group.command("show")
@click.argument("source_id")
@click.pass_context
def inbox_show(ctx: click.Context, source_id: str) -> None:
    """Show one source state and package paths."""
    c = _cli_ctx(ctx)
    state_dir = c["paths"].state_sources
    output_format = c["output_format"]

    state = load_state(state_dir, source_id)
    if state is None:
        fail(f"State file not found for source: {source_id}")

    if output_format == "markdown":
        lines = [f"# Inbox Source: {state.id}", ""]
        lines.append(f"- **connector:** {state.connector}")
        lines.append(f"- **status:** {state.status}")
        if state.document_type:
            lines.append(f"- **document_type:** {state.document_type}")
        if state.origin.url:
            lines.append(f"- **url:** {state.origin.url}")
        if state.origin.title:
            lines.append(f"- **title:** {state.origin.title}")
        if state.origin.author:
            lines.append(f"- **author:** {state.origin.author}")
        if state.origin.external_id:
            lines.append(f"- **external_id:** {state.origin.external_id}")
        if state.content.sha256:
            lines.append(f"- **sha256:** {state.content.sha256}")
        if state.content.estimated_chars:
            lines.append(f"- **estimated_chars:** {state.content.estimated_chars}")
        if state.content.size_bytes:
            lines.append(f"- **size_bytes:** {state.content.size_bytes}")
        if state.paths.inbox:
            lines.append(f"- **inbox_path:** `{state.paths.inbox}`")
        if state.paths.raw:
            lines.append(f"- **raw_path:** `{state.paths.raw}`")
        lines.append(f"- **pageindex.status:** {state.pageindex.status or 'none'}")
        if state.pageindex.artifact_path:
            lines.append(f"- **pageindex.artifact:** `{state.pageindex.artifact_path}`")
        if state.excluded.reason:
            lines.append(f"- **excluded:** {state.excluded.reason} — {state.excluded.note or ''}")
        if state.last_error.message:
            lines.append(f"- **last_error:** [{state.last_error.phase}] {state.last_error.message}")
        if state.runs.last_sync:
            lines.append(f"- **last_sync:** {state.runs.last_sync}")
        click.echo("\n".join(lines))
    else:
        _echo_json(state.to_dict())


@inbox_group.command("mark-processed")
@click.argument("source_id")
@click.option("--session", type=click.Path(), default=None, help="Session file path")
@click.option("--history-note", default=None, help="Short reason for history log")
@click.pass_context
def inbox_mark_processed(ctx: click.Context, source_id: str, session: str | None, history_note: str | None) -> None:
    """Record that an agent processed a source and move its package to raw."""
    c = _cli_ctx(ctx)
    paths = c["paths"]
    state_dir = paths.state_sources
    dry_run = c["dry_run"]
    verbose = c["verbose"]

    state = load_state(state_dir, source_id)
    if state is None:
        fail(f"State file not found for source: {source_id}")

    if state.status == SourceStatus.PROCESSED.value:
        fail(f"Source {source_id} is already marked as processed")

    if verbose:
        click.echo(f"Processing source: {source_id}", err=True)
        click.echo(f"  inbox_path: {state.paths.inbox}", err=True)
        click.echo(f"  raw_path will be: raw/{state.connector}/{Path(state.paths.inbox or '').name}", err=True)

    if dry_run:
        click.echo(f"DRY RUN: would move {source_id} from inbox to raw", err=True)
        _echo_json({
            "source_id": source_id,
            "dry_run": True,
            "from_status": state.status,
            "to_status": SourceStatus.PROCESSED.value,
        })
        return

    inbox_dir = paths.inbox / state.connector
    raw_dir = paths.raw / state.connector
    raw_dir.mkdir(parents=True, exist_ok=True)

    source_folder_name = None
    if state.paths.inbox:
        source_folder_name = Path(state.paths.inbox).name

    if source_folder_name:
        source_inbox_path = inbox_dir / source_folder_name
        source_raw_path = raw_dir / source_folder_name

        if source_inbox_path.exists():
            if verbose:
                click.echo(f"  moving {source_inbox_path} -> {source_raw_path}", err=True)
            shutil.move(str(source_inbox_path), str(source_raw_path))
        else:
            if verbose:
                click.echo(f"  inbox folder not found at {source_inbox_path}", err=True)

    state.status = SourceStatus.PROCESSED.value
    state.paths.raw = f"{state.connector}/{source_folder_name}" if source_folder_name else None
    state.runs.last_sync = datetime.now(timezone.utc).isoformat()

    if history_note:
        state.excluded.reason = "processed"
        state.excluded.note = history_note

    save_state(state_dir, state)

    if history_note:
        history_dir = paths.history
        history_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        history_file = history_dir / f"{timestamp}.log"
        entry = f"{datetime.now(timezone.utc).isoformat()}  processed  {source_id}  {history_note}\n"
        with open(history_file, "a") as f:
            f.write(entry)

    result = {
        "source_id": source_id,
        "status": SourceStatus.PROCESSED.value,
        "moved": source_folder_name is not None,
    }

    if c["output_format"] == "markdown":
        lines = [f"# Mark Processed: {source_id}", "", f"**Status:** processed"]
        if source_folder_name:
            lines.append(f"**Moved:** `inbox/{state.connector}/{source_folder_name}` → `raw/{state.connector}/{source_folder_name}`")
        if history_note:
            lines.append(f"**History note:** {history_note}")
        click.echo("\n".join(lines))
    else:
        _echo_json(result)


@inbox_group.command("run")
@click.option("--max-items", type=int, default=None,
              help="Stop after N successfully processed items (default: drain inbox)")
@click.option("--delay", type=float, default=2.0,
              help="Seconds to sleep between items (default: 2.0)")
@click.option("--cli", "cli_override", type=click.Choice(["claude", "opencode"]), default=None,
              help="Restrict the fallback list to entries matching this CLI")
@click.pass_context
def inbox_run(ctx: click.Context, max_items: int | None, delay: float, cli_override: str | None) -> None:
    """Drain the inbox by spawning external agent sessions, one item at a time.

    Uses the `agents:` fallback list from sources.yaml. Each loop iteration
    spawns a fresh `claude` or `opencode` subprocess that runs the
    /process-inbox skill for exactly one source. When the active agent hits a
    rate limit, the runner advances to the next agent in the list and retries
    the same item. Stops on the first non-rate-limit failure.

    Exit codes:
        0  success / inbox empty / max-items reached
        1  agent failure (non-rate-limit) or no agents configured
        3  fallback list exhausted (all agents rate-limited)
    """
    import time
    start_time = time.time()
    c = _cli_ctx(ctx)
    config = c["config"]
    agents = list(config.agents)

    if cli_override:
        filtered = [a for a in agents if a.cli == cli_override]
        agents = filtered if filtered else [AgentConfig(cli=cli_override)]

    if not agents:
        fail(
            "No agents configured. Add an `agents:` list to sources.yaml, e.g.:\n"
            "  agents:\n"
            "    - cli: claude\n"
            "      model: claude-opus-4-5\n"
            "    - cli: opencode\n"
            "      model: anthropic/claude-sonnet-4-5"
        )

    report = run_loop(
        paths=c["paths"],
        agents=agents,
        config=c["config"],
        max_items=max_items,
        delay_seconds=delay,
        dry_run=c["dry_run"],
        verbose=c["verbose"],
        cwd=c["wiki_root"],
    )

    payload = report.to_dict()

    # Log structured result
    import time
    _log_result("inbox run", payload, int((time.time() - start_time) * 1000))

    # Also write to --report PATH if given
    report_path = c.get("report_path")
    if report_path:
        report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    if c["output_format"] == "markdown":
        lines = ["# cogforge inbox run", "", f"**Result:** {report.result.value}",
                 f"**Items processed:** {report.items_processed}",
                 f"**Items attempted:** {report.items_attempted}"]
        if report.rate_limit_events:
            lines.append("")
            lines.append(f"## Rate-limit events ({len(report.rate_limit_events)})")
            for e in report.rate_limit_events:
                lines.append(f"- attempt {e['attempt']}: agent[{e['agent_index']}] ({e['agent_cli']})")
        if report.failures:
            lines.append("")
            lines.append(f"## Failures ({len(report.failures)})")
            for f in report.failures:
                lines.append(f"- attempt {f['attempt']}: agent[{f['agent_index']}] rc={f['returncode']}")
        if report.pending_count is not None:
            lines.append("")
            lines.append(f"**Pending:** {report.pending_count}")
        if report.planned_command is not None:
            lines.append(f"**Planned command:** `{' '.join(report.planned_command[:3])} ...`")
        click.echo("\n".join(lines))
    else:
        _echo_json(payload)

    if report.result in (
        LoopResult.SUCCESS,
        LoopResult.INBOX_EMPTY,
        LoopResult.MAX_ITEMS_REACHED,
        LoopResult.DRY_RUN,
    ):
        sys.exit(ExitCode.SUCCESS)
    elif report.result == LoopResult.ALL_RATE_LIMITED:
        sys.exit(ExitCode.PARTIAL_SUCCESS)
    else:
        sys.exit(ExitCode.COMMAND_ERROR)


@inbox_group.command("exclude")
@click.argument("source_id")
@click.option("--reason", type=click.Choice(["duplicate", "irrelevant", "unavailable", "user_rejected", "unsupported"]),
              default="irrelevant", help="Reason for exclusion")
@click.option("--note", default=None, help="Optional note")
@click.pass_context
def inbox_exclude(ctx: click.Context, source_id: str, reason: str, note: str | None) -> None:
    """Exclude a source from the pipeline."""
    c = _cli_ctx(ctx)
    state_dir = c["paths"].state_sources
    output_format = c["output_format"]
    dry_run = c["dry_run"]

    state = load_state(state_dir, source_id)
    if state is None:
        fail(f"State file not found for source: {source_id}")

    if state.status == SourceStatus.EXCLUDED.value:
        fail(f"Source {source_id} is already excluded")

    if dry_run:
        click.echo(f"DRY RUN: would exclude {source_id} (reason: {reason})", err=True)
        _echo_json({
            "source_id": source_id,
            "dry_run": True,
            "from_status": state.status,
            "to_status": SourceStatus.EXCLUDED.value,
            "reason": reason,
            "note": note,
        })
        return

    state.status = SourceStatus.EXCLUDED.value
    state.excluded.reason = reason
    state.excluded.note = note
    save_state(state_dir, state)

    result = {
        "source_id": source_id,
        "status": SourceStatus.EXCLUDED.value,
        "reason": reason,
        "note": note,
    }

    if output_format == "markdown":
        lines = [f"# Excluded: {source_id}", "", f"**Status:** excluded", f"**Reason:** {reason}"]
        if note:
            lines.append(f"**Note:** {note}")
        click.echo("\n".join(lines))
    else:
        _echo_json(result)


@inbox_group.command("prepare")
@click.argument("source_id")
@click.option("--no-pageindex", is_flag=True, default=False, help="Do not run PageIndex even if required")
@click.option("--force-pageindex", is_flag=True, default=False, help="Re-run PageIndex even if artifacts exist")
@click.option("--char-threshold", type=int, default=None, help="Override text long-document character threshold")
@click.option("--page-threshold", type=int, default=None, help="Override page threshold")
@click.option("--no-pdf-enrich", is_flag=True, default=False, help="Skip PDF preprocessing for pdf connector sources")
@click.option("--force-pdf-enrich", is_flag=True, default=False, help="Re-run PDF preprocessing even if enriched/ already exists")
@click.option("--allow-missing-vlm-key", is_flag=True, default=False,
              help="Proceed with PDF enrichment even if the VLM API key env var is missing (visual summaries will be skipped instead of producing FAILED placeholders)")
@click.pass_context
def inbox_prepare(ctx: click.Context, source_id: str, no_pageindex: bool, force_pageindex: bool,
                  char_threshold: int | None, page_threshold: int | None,
                  no_pdf_enrich: bool, force_pdf_enrich: bool,
                  allow_missing_vlm_key: bool) -> None:
    """Prepare one or more inbox sources for LLM compilation."""
    c = _cli_ctx(ctx)
    paths = c["paths"]
    config = c["config"]
    output_format = c["output_format"]

    result = prepare_inbox_source(
        source_id=source_id,
        paths=paths,
        config=config,
        no_pageindex=no_pageindex,
        force_pageindex=force_pageindex,
        char_threshold=char_threshold,
        page_threshold=page_threshold,
        no_pdf_enrich=no_pdf_enrich,
        force_pdf_enrich=force_pdf_enrich,
        allow_missing_vlm_key=allow_missing_vlm_key,
    )

    if not result.package_valid:
        fail(f"Source package invalid: {', '.join(result.package_issues)}")
    if result.pdf_enrich_status == "failed":
        hints = result.pdf_enrich_details.get("hints", [])
        msg = "; ".join(hints) if hints else result.pdf_enrich_details.get("error", "unknown error")
        fail(f"PDF enrichment failed: {msg}")

    data = result.to_dict()
    if output_format == "markdown":
        lines = [f"# Prepare: {source_id}", ""]
        lines.append(f"- **connector:** {data.get('connector', 'unknown')}")
        lines.append(f"- **package valid:** {'yes' if result.package_valid else 'no'}")
        for issue in result.package_issues:
            lines.append(f"  - {issue}")
        if result.pdf_enrich_status:
            lines.append(f"- **pdf enrich:** {result.pdf_enrich_status}")
            for k, v in result.pdf_enrich_details.items():
                lines.append(f"  - {k}: {v}")
        lines.append(f"- **long document:** {'yes' if result.long_document_detected else 'no'}")
        if result.pageindex_status:
            lines.append(f"- **pageindex status:** {result.pageindex_status}")
            if result.pageindex_artifact_path:
                lines.append(f"  - artifacts: `{result.pageindex_artifact_path}`")
            if result.pageindex_error:
                lines.append(f"  - error: {result.pageindex_error}")
        click.echo("\n".join(lines))
    else:
        _echo_json(data)


# ── pageindex ────────────────────────────────────────────────────────────────

@main.group("pageindex")
@click.pass_context
def pageindex_group(ctx: click.Context) -> None:
    """Manage PageIndex artifacts for long documents."""


@pageindex_group.command("detect")
@click.argument("source_id", required=False)
@click.option("--char-threshold", type=int, default=None, help="Override character threshold")
@click.option("--page-threshold", type=int, default=None, help="Override page threshold")
@click.pass_context
def pageindex_detect(ctx: click.Context, source_id: str | None, char_threshold: int | None, page_threshold: int | None) -> None:
    """Detect whether sources require PageIndex based on document length."""
    c = _cli_ctx(ctx)
    paths = c["paths"]
    config = c["config"]
    state_dir = paths.state_sources
    output_format = c["output_format"]

    results = []

    if source_id:
        state = load_state(state_dir, source_id)
        if state is None:
            fail(f"State file not found for source: {source_id}")
        states = [state]
    else:
        states = []
        if state_dir.is_dir():
            for state_file in sorted(state_dir.glob("*.yaml")):
                try:
                    state = load_state(state_dir, decode_source_id(state_file.stem))
                except Exception:
                    continue
                if state is None or not state.id:
                    continue
                states.append(state)

    for state in states:
        is_long = detect_long_document(state, config, char_threshold, page_threshold)
        results.append({
            "source_id": state.id,
            "long_document": is_long,
            "estimated_chars": state.content.estimated_chars,
            "estimated_pages": state.content.estimated_pages,
            "current_status": state.pageindex.status,
        })

    result = {
        "sources": results,
        "count": len(results),
        "thresholds": {
            "char_threshold": char_threshold if char_threshold is not None else config.long_document.char_threshold,
            "page_threshold": page_threshold if page_threshold is not None else config.long_document.page_threshold,
        },
    }

    if output_format == "markdown":
        lines = ["# PageIndex Detection"]
        lines.append(f"**Char threshold:** {result['thresholds']['char_threshold']}")
        lines.append(f"**Page threshold:** {result['thresholds']['page_threshold']}")
        lines.append("")
        for r in results:
            icon = "📄" if r["long_document"] else "📃"
            lines.append(f"- {icon} `{r['source_id']}` - {'requires' if r['long_document'] else 'no'} PageIndex"
                         f" ({r['estimated_chars'] or 0} chars)")
        click.echo("\n".join(lines))
    else:
        _echo_json(result)


@pageindex_group.command("run")
@click.argument("source_id")
@click.option("--force", is_flag=True, default=False, help="Re-run even when artifacts exist")
@click.option("--char-threshold", type=int, default=None, help="Override character threshold")
@click.option("--page-threshold", type=int, default=None, help="Override page threshold")
@click.pass_context
def pageindex_run(ctx: click.Context, source_id: str, force: bool, char_threshold: int | None, page_threshold: int | None) -> None:
    """Run PageIndex for one source."""
    c = _cli_ctx(ctx)
    paths = c["paths"]
    config = c["config"]
    state_dir = paths.state_sources
    output_format = c["output_format"]

    state = load_state(state_dir, source_id)
    if state is None:
        fail(f"State file not found for source: {source_id}")

    result = run_pageindex(
        state, paths, config,
        force=force,
        char_override=char_threshold,
        page_override=page_threshold,
    )

    state.pageindex.required = result.required
    state.pageindex.status = result.status
    state.pageindex.artifact_path = result.artifact_path
    state.pageindex.error = result.error
    save_state(state_dir, state)

    if output_format == "markdown":
        lines = [f"# PageIndex Run: {source_id}", ""]
        lines.append(f"- **required:** {result.required}")
        lines.append(f"- **status:** {result.status}")
        if result.artifact_path:
            lines.append(f"- **artifacts:** `{result.artifact_path}`")
        if result.error:
            lines.append(f"- **error:** {result.error}")
        if result.page_count is not None:
            lines.append(f"- **pages:** {result.page_count}")
        click.echo("\n".join(lines))
    else:
        _echo_json({
            "source_id": source_id,
            "required": result.required,
            "status": result.status,
            "artifact_path": result.artifact_path,
            "error": result.error,
            "page_count": result.page_count,
        })


@pageindex_group.command("show")
@click.argument("source_id")
@click.pass_context
def pageindex_show(ctx: click.Context, source_id: str) -> None:
    """Show artifact paths and summary metadata for one source."""
    c = _cli_ctx(ctx)
    paths = c["paths"]
    state_dir = paths.state_sources
    output_format = c["output_format"]

    state = load_state(state_dir, source_id)
    if state is None:
        fail(f"State file not found for source: {source_id}")

    pi = state.pageindex
    connector_dir = state.connector
    source_id_encoded = encode_source_id(source_id)

    artifact_base = paths.connector_pageindex(connector_dir, source_id_encoded)

    if output_format == "markdown":
        lines = [f"# PageIndex: {source_id}", ""]
        lines.append(f"- **required:** {pi.required}")
        lines.append(f"- **status:** {pi.status or 'none'}")
        artifact_path_display = pi.artifact_path or str(artifact_base)
        lines.append(f"- **artifact_path:** `{artifact_path_display}`")
        if pi.error:
            lines.append(f"- **error:** {pi.error}")
        if artifact_base.is_dir():
            lines.append("")
            lines.append("## Artifact Files")
            for f in sorted(artifact_base.glob("*")):
                if f.is_file():
                    lines.append(f"- `{f.name}` ({f.stat().st_size} bytes)")
        click.echo("\n".join(lines))
    else:
        artifacts = {}
        if artifact_base.is_dir():
            for f in sorted(artifact_base.glob("*")):
                if f.is_file():
                    artifacts[f.name] = str(f)
        _echo_json({
            "source_id": source_id,
            "required": pi.required,
            "status": pi.status,
            "artifact_path": pi.artifact_path,
            "error": pi.error,
            "artifacts": artifacts,
        })


# ── wiki ────────────────────────────────────────────────────────────────────

@main.group("wiki")
@click.pass_context
def wiki_group(ctx: click.Context) -> None:
    """Wiki bookkeeping operations."""


@wiki_group.command("validate")
@click.pass_context
def wiki_validate(ctx: click.Context) -> None:
    """Validate wiki structure."""
    c = _cli_ctx(ctx)
    required_dirs = ["inbox", "raw", ".llmkb/state/sources", ".llmkb/reports", "wiki", "history"]
    missing = [d for d in required_dirs if not (c["wiki_root"] / d).is_dir()]
    present = [d for d in required_dirs if (c["wiki_root"] / d).is_dir()]

    result = {
        "wiki_root": str(c["wiki_root"]),
        "valid": len(missing) == 0,
        "present": present,
        "missing": missing,
    }

    if c["output_format"] == "markdown":
        lines = ["# Wiki Validation"]
        if result["valid"]:
            lines.append("Wiki structure is valid.")
        else:
            lines.append(f"Missing {len(missing)} required directories:")
            for m in missing:
                lines.append(f"- `{m}`")
        click.echo("\n".join(lines))
    else:
        _echo_json(result)

    if missing:
        sys.exit(ExitCode.VALIDATION_FAILED)


@wiki_group.command("log")
@click.option("--message", required=True, help="Log message to append")
@click.option("--session", type=click.Path(), default=None, help="Session file path for context")
@click.pass_context
def wiki_log(ctx: click.Context, message: str, session: str | None) -> None:
    """Append a timestamped entry to the daily history log."""
    c = _cli_ctx(ctx)
    history_dir = c["paths"].history
    history_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc)
    date_str = timestamp.strftime("%Y-%m-%d")
    time_str = timestamp.strftime("%H:%M:%S")
    history_file = history_dir / f"{date_str}.log"

    entry = f"{time_str}  {message}"
    if session:
        entry += f"  session={session}"
    entry += "\n"

    with open(history_file, "a") as f:
        f.write(entry)

    result = {
        "date": date_str,
        "time": time_str,
        "message": message,
        "file": str(history_file),
    }

    if c["output_format"] == "markdown":
        click.echo(f"# Wiki Log Entry\n\n**Date:** {date_str}\n**Time:** {time_str}\n**Message:** {message}")
    else:
        _echo_json(result)


@wiki_group.command("session-new")
@click.option("--summary", default=None, help="One-line summary of the session")
@click.option("--domain", default=None, help="Domain name (trading, miniature-painting, etc.)")
@click.option("--files-changed", default=None, help="Comma-separated list of changed file paths")
@click.option("--decisions", default=None, help="Comma-separated list of decisions made")
@click.option("--next-steps", default=None, help="Comma-separated list of next steps")
@click.option("--session-id", default=None, help="Optional explicit session ID (defaults to timestamp)")
@click.pass_context
def wiki_session_new(ctx: click.Context, summary: str | None, domain: str | None, files_changed: str | None, decisions: str | None, next_steps: str | None, session_id: str | None) -> None:
    """Create a new session YAML from metadata flags."""
    c = _cli_ctx(ctx)
    paths = c["paths"]
    output_format = c["output_format"]

    sessions_dir = paths.history / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc)
    sid = session_id or timestamp.strftime("%Y-%m-%dT%H-%M-%S")
    session_file = sessions_dir / f"{sid}.yaml"

    session_data: dict[str, Any] = {
        "version": 1,
        "id": sid,
        "created_at": timestamp.isoformat(),
    }

    if summary:
        session_data["summary"] = summary
    if domain:
        session_data["domain"] = domain
    if files_changed:
        session_data["files_changed"] = [f.strip() for f in files_changed.split(",") if f.strip()]
    if decisions:
        session_data["decisions"] = [d.strip() for d in decisions.split(",") if d.strip()]
    if next_steps:
        session_data["next_steps"] = [n.strip() for n in next_steps.split(",") if n.strip()]

    with open(session_file, "w") as f:
        yaml.dump(session_data, f, default_flow_style=False, sort_keys=False)

    result = {
        "session_id": sid,
        "session_file": str(session_file),
        "files_changed_count": len(session_data.get("files_changed", [])),
        "decisions_count": len(session_data.get("decisions", [])),
    }

    if output_format == "markdown":
        lines = [
            f"# Session: {sid}",
            "",
            f"**Created:** {timestamp.isoformat()}",
        ]
        if summary:
            lines.append(f"**Summary:** {summary}")
        if domain:
            lines.append(f"**Domain:** {domain}")
        if files_changed:
            lines.append(f"\n**Files changed ({len(session_data.get('files_changed', []))}):**")
            for fp in session_data.get("files_changed", []):
                lines.append(f"- `{fp}`")
        if decisions:
            lines.append(f"\n**Decisions ({len(session_data.get('decisions', []))}):**")
            for d in session_data.get("decisions", []):
                lines.append(f"- {d}")
        if next_steps:
            lines.append(f"\n**Next steps ({len(session_data.get('next_steps', []))}):**")
            for ns in session_data.get("next_steps", []):
                lines.append(f"- {ns}")
        lines.append(f"\n**File:** `{session_file}`")
        click.echo("\n".join(lines))
    else:
        _echo_json(result)


@wiki_group.command("session-close")
@click.option("--report", type=click.Path(exists=True), required=True, help="Report file to create session from")
@click.pass_context
def wiki_session_close(ctx: click.Context, report: Path) -> None:
    """Create or update a session YAML from a structured report."""
    c = _cli_ctx(ctx)
    paths = c["paths"]
    output_format = c["output_format"]

    report_data = load_report(paths.reports, report.stem)
    if report_data is None:
        # Try reading directly from the given path
        with open(report) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            fail(f"Invalid report file: {report}")
        report_data = Report.from_dict(data)

    sessions_dir = paths.root / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc)
    session_id = timestamp.strftime("%Y-%m-%dT%H-%M-%S")
    session_file = sessions_dir / f"{session_id}.yaml"

    session_data = {
        "version": 1,
        "id": session_id,
        "created_at": timestamp.isoformat(),
        "report_source": str(report),
        "summary": report_data.changes.summary if report_data.changes else "",
        "items_count": len(report_data.items) if report_data.items else 0,
        "errors": report_data.summary.errors if report_data.summary else 0,
        "warnings": report_data.summary.warnings if report_data.summary else 0,
    }

    with open(session_file, "w") as f:
        yaml.dump(session_data, f, default_flow_style=False, sort_keys=False)

    result = {
        "session_id": session_id,
        "session_file": str(session_file),
        "items_count": session_data["items_count"],
        "errors": session_data["errors"],
        "warnings": session_data["warnings"],
    }

    if output_format == "markdown":
        lines = [
            f"# Session Closed: {session_id}",
            "",
            f"**Source:** `{report}`",
            f"**Items:** {session_data['items_count']}",
            f"**Errors:** {session_data['errors']}",
            f"**Warnings:** {session_data['warnings']}",
            f"**File:** `{session_file}`",
        ]
        click.echo("\n".join(lines))
    else:
        _echo_json(result)



# ── skills ──────────────────────────────────────────────────────────────────

@main.command("skills")
@click.option("--check", is_flag=True, default=False, help="Report whether local skills match canonical versions without writing.")
@click.option("--agent", type=click.Choice(["opencode", "claude", "all"]), default="all", help="Agent target to sync.")
@click.pass_context
def skills_cmd(ctx: click.Context, check: bool, agent: str) -> None:
    """Sync canonical Cogforge skills into the local project agent directories.

    Skills are part of the Cogforge software and are managed, not user-edited.
    Auto-sync runs silently on every cogforge command inside a Cogforge repo.
    """
    c = _cli_ctx(ctx)
    wiki_root = c.get("wiki_root", Path.cwd())
    project_root = wiki_root.parent
    dry_run = c.get("dry_run", False)

    if not _is_cogforge_repo(project_root):
        fail("Not inside a Cogforge-managed repository. Run cogforge init first.")

    agents = ["opencode", "claude"] if agent == "all" else [agent]

    if check:
        report = check_skills(project_root)
        if c.get("output_format") == "markdown":
            lines = ["# cogforge skills --check", ""]
            if report["ok"]:
                lines.append("**Status:** OK — all skills up to date.")
            else:
                lines.append("**Status:** STALE or MISSING")
                if report["missing"]:
                    lines.append(f"**Missing:** {len(report['missing'])}")
                    for m in report["missing"]:
                        lines.append(f"- {m['agent']}/{m['name']}")
                if report["stale"]:
                    lines.append(f"**Stale:** {len(report['stale'])}")
                    for s in report["stale"]:
                        lines.append(f"- {s['agent']}/{s['name']}")
            click.echo("\n".join(lines))
        else:
            _echo_json(report)
        return

    result = sync_skills(project_root, agents=agents, dry_run=dry_run)
    if c.get("output_format") == "markdown":
        lines = ["# cogforge skills", ""]
        if dry_run:
            lines.append("**Dry run** — no files written.")
        lines.append(f"**Synced:** {len(result['synced'])}")
        for item in result["synced"]:
            lines.append(f"- {item['agent']} {item['type']} `{item['name']}` → {item['dst']}")
        if result["errors"]:
            lines.append(f"**Errors:** {len(result['errors'])}")
            for e in result["errors"]:
                lines.append(f"- {e}")
        click.echo("\n".join(lines))
    else:
        _echo_json(result)


if __name__ == "__main__":
    main()
