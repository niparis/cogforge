"""Canonical run report model and rendering for cogforge."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ReportSummary:
    sources_seen: int = 0
    sources_created: int = 0
    sources_updated: int = 0
    sources_failed: int = 0
    sources_excluded: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ReportSummary":
        if data is None:
            return cls()
        return cls(
            sources_seen=data.get("sources_seen", 0),
            sources_created=data.get("sources_created", 0),
            sources_updated=data.get("sources_updated", 0),
            sources_failed=data.get("sources_failed", 0),
            sources_excluded=data.get("sources_excluded", 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources_seen": self.sources_seen,
            "sources_created": self.sources_created,
            "sources_updated": self.sources_updated,
            "sources_failed": self.sources_failed,
            "sources_excluded": self.sources_excluded,
        }


@dataclass
class ReportChanges:
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    files_moved: list[str] = field(default_factory=list)
    files_deleted: list[str] = field(default_factory=list)
    states_created: list[str] = field(default_factory=list)
    states_updated: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ReportChanges":
        if data is None:
            return cls()
        return cls(
            files_created=data.get("files_created", []),
            files_modified=data.get("files_modified", []),
            files_moved=data.get("files_moved", []),
            files_deleted=data.get("files_deleted", []),
            states_created=data.get("states_created", []),
            states_updated=data.get("states_updated", []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_created": self.files_created,
            "files_modified": self.files_modified,
            "files_moved": self.files_moved,
            "files_deleted": self.files_deleted,
            "states_created": self.states_created,
            "states_updated": self.states_updated,
        }


@dataclass
class ReportItem:
    source_id: str = ""
    action: str = ""
    message: str = ""
    requires_llm_judgment: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReportItem":
        return cls(
            source_id=data.get("source_id", ""),
            action=data.get("action", ""),
            message=data.get("message", ""),
            requires_llm_judgment=data.get("requires_llm_judgment", False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "action": self.action,
            "message": self.message,
            "requires_llm_judgment": self.requires_llm_judgment,
        }


@dataclass
class Report:
    version: int = 1
    run_id: str = ""
    command: str = ""
    started_at: str = ""
    finished_at: str = ""
    status: str = "success"  # success | partial | failed

    summary: ReportSummary = field(default_factory=ReportSummary)
    changes: ReportChanges = field(default_factory=ReportChanges)
    items: list[ReportItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    next_commands: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Report":
        return cls(
            version=data.get("version", 1),
            run_id=data.get("run_id", ""),
            command=data.get("command", ""),
            started_at=data.get("started_at", ""),
            finished_at=data.get("finished_at", ""),
            status=data.get("status", "success"),
            summary=ReportSummary.from_dict(data.get("summary")),
            changes=ReportChanges.from_dict(data.get("changes")),
            items=[ReportItem.from_dict(i) for i in data.get("items", [])],
            errors=data.get("errors", []),
            next_commands=data.get("next_commands", []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "run_id": self.run_id,
            "command": self.command,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "summary": self.summary.to_dict(),
            "changes": self.changes.to_dict(),
            "items": [i.to_dict() for i in self.items],
            "errors": self.errors,
            "next_commands": self.next_commands,
        }


def load_report(reports_dir: Path, run_id: str) -> Report | None:
    """Load a report from the reports directory."""
    fpath = reports_dir / f"{run_id}.yaml"
    if not fpath.is_file():
        return None
    with open(fpath) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return None
    return Report.from_dict(data)


def save_report(reports_dir: Path, report: Report) -> Path:
    """Persist a report to the reports directory."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    fpath = reports_dir / f"{report.run_id}.yaml"
    with open(fpath, "w") as f:
        yaml.dump(report.to_dict(), f, default_flow_style=False, sort_keys=False)
    return fpath


def render_json(report: Report) -> str:
    """Render a report as JSON."""
    import json
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)


def render_markdown(report: Report) -> str:
    """Render a report as Markdown."""
    lines = [
        f"# Run Report: {report.run_id}",
        "",
        f"**Command:** `{report.command}`",
        f"**Status:** {report.status}",
        f"**Started:** {report.started_at or 'N/A'}",
        f"**Finished:** {report.finished_at or 'N/A'}",
        "",
        "## Summary",
        "",
        f"- Sources seen: {report.summary.sources_seen}",
        f"- Sources created: {report.summary.sources_created}",
        f"- Sources updated: {report.summary.sources_updated}",
        f"- Sources failed: {report.summary.sources_failed}",
        f"- Sources excluded: {report.summary.sources_excluded}",
    ]

    if report.changes.files_created:
        lines.append("")
        lines.append("## Files Created")
        for f in report.changes.files_created:
            lines.append(f"- `{f}`")

    if report.changes.files_modified:
        lines.append("")
        lines.append("## Files Modified")
        for f in report.changes.files_modified:
            lines.append(f"- `{f}`")

    if report.items:
        lines.append("")
        lines.append("## Items")
        for item in report.items:
            lines.append(f"- **{item.action}** `{item.source_id}`: {item.message}")

    if report.errors:
        lines.append("")
        lines.append("## Errors")
        for e in report.errors:
            lines.append(f"- {e}")

    if report.next_commands:
        lines.append("")
        lines.append("## Suggested Next Commands")
        for cmd in report.next_commands:
            lines.append(f"- `{cmd}`")

    lines.append("")
    return "\n".join(lines)
