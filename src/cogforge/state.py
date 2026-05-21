"""Source state model and lifecycle management."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml


class SourceStatus(str, Enum):
    INBOX = "inbox"
    PROCESSED = "processed"
    FAILED = "failed"
    EXCLUDED = "excluded"
    AUDIO_ONLY = "audio_only"


@dataclass
class Origin:
    url: str | None = None
    external_id: str | None = None
    parent_source_id: str | None = None
    title: str | None = None
    author: str | None = None
    fetched_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Origin":
        if data is None:
            return cls()
        return cls(
            url=data.get("url"),
            external_id=data.get("external_id"),
            parent_source_id=data.get("parent_source_id"),
            title=data.get("title"),
            author=data.get("author"),
            fetched_at=data.get("fetched_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v for k, v in {
                "url": self.url,
                "external_id": self.external_id,
                "parent_source_id": self.parent_source_id,
                "title": self.title,
                "author": self.author,
                "fetched_at": self.fetched_at,
            }.items() if v is not None
        }


@dataclass
class ContentInfo:
    sha256: str | None = None
    size_bytes: int | None = None
    estimated_chars: int | None = None
    estimated_pages: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ContentInfo":
        if data is None:
            return cls()
        return cls(
            sha256=data.get("sha256"),
            size_bytes=data.get("size_bytes"),
            estimated_chars=data.get("estimated_chars"),
            estimated_pages=data.get("estimated_pages"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v for k, v in {
                "sha256": self.sha256,
                "size_bytes": self.size_bytes,
                "estimated_chars": self.estimated_chars,
                "estimated_pages": self.estimated_pages,
            }.items() if v is not None
        }


@dataclass
class SourcePaths:
    inbox: str | None = None
    raw: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SourcePaths":
        if data is None:
            return cls()
        return cls(inbox=data.get("inbox"), raw=data.get("raw"))

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v for k, v in {"inbox": self.inbox, "raw": self.raw}.items()
            if v is not None
        }


@dataclass
class PageIndexInfo:
    required: bool = False
    status: str | None = None
    artifact_path: str | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PageIndexInfo":
        if data is None:
            return cls()
        return cls(
            required=data.get("required", False),
            status=data.get("status"),
            artifact_path=data.get("artifact_path"),
            error=data.get("error"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v for k, v in {
                "required": self.required if self.required else None,
                "status": self.status,
                "artifact_path": self.artifact_path,
                "error": self.error,
            }.items() if v is not None
        }


@dataclass
class ExcludedInfo:
    reason: str | None = None
    note: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ExcludedInfo":
        if data is None:
            return cls()
        return cls(reason=data.get("reason"), note=data.get("note"))

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v for k, v in {"reason": self.reason, "note": self.note}.items()
            if v is not None
        }


@dataclass
class LastError:
    phase: str | None = None
    message: str | None = None
    retryable: bool = False
    occurred_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "LastError":
        if data is None:
            return cls()
        return cls(
            phase=data.get("phase"),
            message=data.get("message"),
            retryable=data.get("retryable", False),
            occurred_at=data.get("occurred_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v for k, v in {
                "phase": self.phase,
                "message": self.message,
                "retryable": self.retryable if self.retryable else None,
                "occurred_at": self.occurred_at,
            }.items() if v is not None
        }


@dataclass
class RunsInfo:
    last_sync: str | None = None
    last_pageindex: str | None = None
    last_archive: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RunsInfo":
        if data is None:
            return cls()
        return cls(
            last_sync=data.get("last_sync"),
            last_pageindex=data.get("last_pageindex"),
            last_archive=data.get("last_archive"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v for k, v in {
                "last_sync": self.last_sync,
                "last_pageindex": self.last_pageindex,
                "last_archive": self.last_archive,
            }.items() if v is not None
        }


@dataclass
class SourceState:
    """Canonical source state per architecture spec."""
    version: int = 1
    id: str = ""
    connector: str = ""
    document_type: str | None = None
    status: str = SourceStatus.INBOX.value

    origin: Origin = field(default_factory=Origin)
    content: ContentInfo = field(default_factory=ContentInfo)
    paths: SourcePaths = field(default_factory=SourcePaths)
    pageindex: PageIndexInfo = field(default_factory=PageIndexInfo)
    last_error: LastError = field(default_factory=LastError)
    excluded: ExcludedInfo = field(default_factory=ExcludedInfo)
    runs: RunsInfo = field(default_factory=RunsInfo)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceState":
        return cls(
            version=data.get("version", 1),
            id=data.get("id", ""),
            connector=data.get("connector", ""),
            document_type=data.get("document_type"),
            status=data.get("status", SourceStatus.INBOX.value),
            origin=Origin.from_dict(data.get("origin")),
            content=ContentInfo.from_dict(data.get("content")),
            paths=SourcePaths.from_dict(data.get("paths")),
            pageindex=PageIndexInfo.from_dict(data.get("pageindex")),
            last_error=LastError.from_dict(data.get("last_error")),
            excluded=ExcludedInfo.from_dict(data.get("excluded")),
            runs=RunsInfo.from_dict(data.get("runs")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "id": self.id,
            "connector": self.connector,
            "document_type": self.document_type,
            "status": self.status,
            "origin": self.origin.to_dict(),
            "content": self.content.to_dict(),
            "paths": self.paths.to_dict(),
            "pageindex": self.pageindex.to_dict(),
            "last_error": self.last_error.to_dict(),
            "excluded": self.excluded.to_dict(),
            "runs": self.runs.to_dict(),
        }


def encode_source_id(source_id: str) -> str:
    """Encode source ID for filesystem-safe state filenames."""
    return source_id.replace(":", "__").replace("/", "__")


def decode_source_id(stem: str) -> str:
    """Decode source ID from filesystem stem (reverses encode_source_id)."""
    # First __ back to :, remaining __ back to /
    return stem.replace("__", ":", 1).replace("__", "/")


def load_state(state_dir: Path, source_id: str) -> SourceState | None:
    """Load a source state file by source ID."""
    fname = encode_source_id(source_id) + ".yaml"
    state_file = state_dir / fname
    if not state_file.is_file():
        return None
    with open(state_file) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return None
    return SourceState.from_dict(data)


def save_state(state_dir: Path, state: SourceState) -> Path:
    """Save a source state file."""
    state_dir.mkdir(parents=True, exist_ok=True)
    data = state.to_dict()
    fname = encode_source_id(state.id) + ".yaml"
    state_file = state_dir / fname
    with open(state_file, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return state_file


def list_source_states(
    state_dir: Path,
    *,
    status: str | None = None,
    connector: str | None = None,
    pageindex_status: str | None = None,
    failed_only: bool = False,
) -> list[SourceState]:
    """Load and filter source state files from a state directory.

    Filters:
        status: only return states with this status (e.g. SourceStatus.INBOX.value).
                Ignored if `failed_only=True`.
        connector: only return states with this connector name.
        pageindex_status: only return states whose pageindex.status matches.
        failed_only: shortcut for status=SourceStatus.FAILED.value.

    Returns an empty list if the state directory does not exist.
    """
    out: list[SourceState] = []
    if not state_dir.is_dir():
        return out

    for state_file in sorted(state_dir.glob("*.yaml")):
        try:
            state = load_state(state_dir, decode_source_id(state_file.stem))
        except Exception:
            continue
        if state is None or not state.id:
            continue

        if failed_only:
            if state.status != SourceStatus.FAILED.value:
                continue
        elif status is not None and state.status != status:
            continue

        if connector and state.connector != connector:
            continue
        if pageindex_status and state.pageindex.status != pageindex_status:
            continue

        out.append(state)
    return out


def validate_state(
    state_dir: Path, valid_statuses: set[str] | None = None
) -> dict[str, Any]:
    """Validate all source state files in a state directory.

    Returns dict with valid, errors, warnings, sources_checked.
    """
    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    source_count = 0

    if valid_statuses is None:
        valid_statuses = {s.value for s in SourceStatus}

    if not state_dir.is_dir():
        return {
            "valid": True,
            "errors": [],
            "warnings": ["No state directory found - normal before first sync."],
            "sources_checked": 0,
        }

    for state_file in sorted(state_dir.glob("*.yaml")):
        source_count += 1
        try:
            state = load_state(state_dir, decode_source_id(state_file.stem))
        except Exception as e:
            errors.append(f"{state_file.name}: parse error - {e}")
            continue

        if state is None or not state.id:
            errors.append(f"{state_file.name}: failed to parse or missing id")
            continue

        if state.id in seen_ids:
            errors.append(f"Duplicate source ID: {state.id}")
        seen_ids.add(state.id)

        if state.status not in valid_statuses:
            errors.append(
                f"{state_file.name}: invalid status '{state.status}' "
                f"(valid: {', '.join(sorted(valid_statuses))})"
            )

        if state.status == SourceStatus.PROCESSED.value and not state.paths.raw:
            warnings.append(f"{state_file.name}: processed status but no raw path")

        if state.status == SourceStatus.FAILED.value and not state.last_error.message:
            warnings.append(f"{state_file.name}: failed status but no error message")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "sources_checked": source_count,
    }
