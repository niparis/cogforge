"""Path resolution utilities for the cogforge wiki."""
from pathlib import Path


class Paths:
    """Computes wiki subdirectory paths from a root."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def inbox(self) -> Path:
        return self.root / "inbox"

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def pageindex(self) -> Path:
        return self.root / "pageindex"

    @property
    def state_sources(self) -> Path:
        return self.root / ".llmkb" / "state" / "sources"

    @property
    def reports(self) -> Path:
        return self.root / ".llmkb" / "reports"

    @property
    def history(self) -> Path:
        return self.root / "history"

    @property
    def history_sessions(self) -> Path:
        return self.root / "history" / "sessions"

    @property
    def wiki(self) -> Path:
        return self.root / "wiki"

    @property
    def papers(self) -> Path:
        return self.raw / "papers"

    def connector_inbox(self, connector: str) -> Path:
        return self.inbox / connector

    def connector_raw(self, connector: str) -> Path:
        return self.raw / connector

    def connector_pageindex(self, connector: str, source_id: str) -> Path:
        return self.pageindex / connector / source_id

    def state_file(self, source_id: str) -> Path:
        return self.state_sources / f"{_encode_source_id(source_id)}.yaml"

    def report_file(self, run_id: str) -> Path:
        return self.reports / f"{run_id}.yaml"

    def ensure(self) -> None:
        """Create all required directories."""
        for d in [
            self.inbox,
            self.raw,
            self.pageindex,
            self.state_sources,
            self.reports,
            self.history,
            self.history_sessions,
            self.wiki,
        ]:
            d.mkdir(parents=True, exist_ok=True)


def resolve_wiki_root(cwd: Path | None = None) -> Path:
    """Walk up from cwd to find llm_wiki directory, or return cwd/llm_wiki."""
    start = cwd or Path.cwd()
    for parent in [start, *start.parents]:
        candidate = parent / "llm_wiki"
        if candidate.is_dir():
            return candidate
    return start / "llm_wiki"


def _encode_source_id(source_id: str) -> str:
    """Encode source ID for safe filesystem use."""
    return source_id.replace(":", "__").replace("/", "__")


def _decode_source_id(stem: str) -> str:
    """Decode source ID from filesystem stem."""
    return stem.replace("__", ":", 1).replace("__", "/")
