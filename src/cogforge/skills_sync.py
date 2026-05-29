"""Canonical skill sync: copy packaged skills into project-local agent directories.

Skills are part of the Cogforge software. They are managed, not user-edited.
Auto-sync copies all bundled skills on every run inside a Cogforge-managed repo.
"""
from __future__ import annotations

import shutil
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any


# Supported agent types and their local directory layout
_AGENT_TARGETS: dict[str, dict[str, Path | str]] = {
    "opencode": {
        "skills_dir": Path(".opencode") / "skills",
        "agents_dir": Path(".opencode") / "agents",
    },
    "claude": {
        "skills_dir": Path(".claude") / "skills",
        "agents_dir": Path(".claude") / "agents",
    },
}

_CANONICAL_SKILL_NAMES = [
    "answer",
    "create-synthesis",
    "lint-wiki",
    "log-change",
    "persist-decision",
    "process-inbox",
    "session-memory",
    "update-domain-context",
    "youtube-transcript",
]

_AGENT_ASSETS = {
    "inbox-processor-instructions.md",
}


def _is_cogforge_repo(project_root: Path) -> bool:
    """Detect whether a directory looks like a Cogforge-managed repo.

    Accepts either the project root (where sources.yaml lives) or the
    llm_wiki subdirectory.
    """
    markers = ["sources.yaml", "llm_wiki", "AGENTS.md"]
    if any((project_root / m).exists() for m in markers):
        return True
    # Also accept if project_root is inside llm_wiki (check parent)
    parent = project_root.parent
    if parent != project_root and any((parent / m).exists() for m in markers):
        return True
    return False


def sync_skills(
    project_root: Path,
    *,
    agents: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Copy canonical skills from the Cogforge package into the project.

    Args:
        project_root: root of the target project (where .opencode/.claude live).
        agents: list of agents to sync, e.g. ["opencode", "claude"].
                None means both.
        dry_run: if True, compute what would change without writing.

    Returns:
        dict with keys: synced (list of dicts), skipped (list), errors (list)
    """
    if agents is None:
        agents = list(_AGENT_TARGETS.keys())

    result: dict[str, Any] = {"synced": [], "skipped": [], "errors": []}

    with as_file(files("cogforge.skills")) as skill_root:
        for agent in agents:
            cfg = _AGENT_TARGETS.get(agent)
            if not cfg:
                result["errors"].append({"agent": agent, "reason": "unknown agent"})
                continue

            # Copy skills
            skills_dst = project_root / cfg["skills_dir"]
            for name in _CANONICAL_SKILL_NAMES:
                src = skill_root / name / "SKILL.md"
                dst = skills_dst / name / "SKILL.md"
                if not src.exists():
                    result["errors"].append({"agent": agent, "skill": name, "reason": "canonical missing"})
                    continue
                if not dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                result["synced"].append({
                    "agent": agent,
                    "type": "skill",
                    "name": name,
                    "dst": str(dst.relative_to(project_root)),
                })

            # Copy agent prompt assets
            agents_dst = project_root / cfg["agents_dir"]
            for asset in _AGENT_ASSETS:
                src = skill_root / "agents" / asset
                dst = agents_dst / asset
                if not src.exists():
                    continue
                if not dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                result["synced"].append({
                    "agent": agent,
                    "type": "agent-asset",
                    "name": asset,
                    "dst": str(dst.relative_to(project_root)),
                })

    return result


def check_skills(project_root: Path) -> dict[str, Any]:
    """Check whether local skills match canonical versions.

    Returns dict with: ok (bool), missing (list), stale (list).
    """
    missing: list[dict[str, str]] = []
    stale: list[dict[str, str]] = []
    ok = True

    with as_file(files("cogforge.skills")) as skill_root:
        for agent, cfg in _AGENT_TARGETS.items():
            skills_dst = project_root / cfg["skills_dir"]
            for name in _CANONICAL_SKILL_NAMES:
                src = skill_root / name / "SKILL.md"
                dst = skills_dst / name / "SKILL.md"
                if not dst.exists():
                    missing.append({"agent": agent, "name": name})
                    ok = False
                elif src.exists() and src.read_bytes() != dst.read_bytes():
                    stale.append({"agent": agent, "name": name})
                    ok = False

    return {"ok": ok, "missing": missing, "stale": stale}
