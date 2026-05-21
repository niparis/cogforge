"""Migrate old-format YouTube transcripts to the new inbox layout.

Old format: raw/transcripts/<video_id>.md  (flat file with YAML frontmatter)
New format: inbox/youtube/<date>-<slug>--<video_id>/index.md + original.json
            .llmkb/state/sources/youtube__<video_id>.yaml
"""
from __future__ import annotations

import json
from loguru import logger as log
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from cogforge.paths import Paths
from cogforge.state import (
    ContentInfo,
    LastError,
    Origin,
    RunsInfo,
    SourcePaths,
    SourceState,
    load_state,
    save_state,
)
from cogforge.sync_youtube import (
    YouTubeVideo,
    _build_issue_dir,
    _write_issue,
    _write_source_state,
    _build_synced_ids,
)




# ── Parsing old-format files ──────────────────────────────────────────────────

def _parse_frontmatter_line(line: str) -> tuple[str, str] | None:
    """Extract key and value from a single YAML frontmatter line."""
    m = re.match(r'^(\w+):\s*(.*)', line)
    if not m:
        return None
    return m.group(1), m.group(2).strip()


def _parse_old_transcript(path: Path) -> dict[str, Any] | None:
    """Parse frontmatter and body from an old raw/transcripts/<id>.md file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    # Use regex line-by-line extraction so titles with colons don't break parsing
    fm: dict[str, str] = {}
    for line in parts[1].splitlines():
        pair = _parse_frontmatter_line(line)
        if pair:
            fm[pair[0]] = pair[1]

    if not fm:
        return None

    body = parts[2].strip()
    # Strip the heading line that duplicates the title
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[2:] if len(lines) > 1 else []
    transcript = "\n".join(lines).strip()
    return {
        "video_id": fm.get("video_id") or path.stem,
        "title": fm.get("title", ""),
        "channel": fm.get("channel", ""),
        "language": fm.get("language", ""),
        "transcript": transcript,
    }


# ── yt-dlp metadata fetch ────────────────────────────────────────────────────

def _fetch_metadata_ytdlp(video_id: str) -> dict[str, Any] | None:
    """Fetch video metadata via yt-dlp. Returns None on any failure."""
    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--dump-json",
                "--no-download",
                "--no-update",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            log.warning("yt-dlp failed for {}: {}", video_id, result.stderr.strip()[:200])
            return None
        raw = json.loads(result.stdout)
        return {
            "upload_date": raw.get("upload_date", ""),
            "duration_seconds": raw.get("duration", 0) or 0,
            "view_count": raw.get("view_count", 0) or 0,
            "thumbnail_url": raw.get("thumbnail", ""),
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as exc:
        log.warning("yt-dlp error for {}: {}", video_id, exc)
        return None


def _upload_date_to_display(upload_date: str) -> str:
    """Convert yt-dlp YYYYMMDD to YYYY-MM-DD, or return '0000-00-00'."""
    if len(upload_date) >= 8:
        d = upload_date[:8]
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return "0000-00-00"


# ── Migration result ──────────────────────────────────────────────────────────

@dataclass
class MigrateResult:
    migrated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    cleaned_up: list[str] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, Any]:
        return {
            "migrated": len(self.migrated),
            "skipped": len(self.skipped),
            "failed": len(self.failed),
            "cleaned_up": len(self.cleaned_up),
        }


# ── Main migration function ───────────────────────────────────────────────────

def migrate_youtube_transcripts(
    paths: Paths,
    *,
    dry_run: bool = False,
    cleanup: bool = False,
    verbose: bool = False,
    limit: int | None = None,
) -> MigrateResult:
    """Migrate old raw/transcripts/*.md files to the new inbox/youtube/ layout."""
    result = MigrateResult()

    old_dir = paths.root / "raw" / "transcripts"
    if not old_dir.is_dir():
        log.warning("No old transcripts directory found at {}", old_dir)
        return result

    old_files = [f for f in sorted(old_dir.glob("*.md")) if f.stem != ".failed_ids"]

    # Build set of already-migrated IDs (new format on disk)
    synced_ids = _build_synced_ids(paths)

    candidates = []
    for md_file in old_files:
        video_id = md_file.stem
        # Skip if already present in new format
        new_state = load_state(paths.state_sources, f"youtube:{video_id}")
        if new_state and (paths.root / new_state.paths.inbox).is_dir() if new_state and new_state.paths.inbox else False:
            result.skipped.append(video_id)
            if verbose:
                log.info("skip (state+dir exists): {}", video_id)
            continue
        # Skip if a new-format folder already exists on disk
        if video_id in synced_ids and _new_format_exists(paths, video_id):
            result.skipped.append(video_id)
            if verbose:
                log.info("skip (new dir on disk): {}", video_id)
            continue
        candidates.append(md_file)

    if limit is not None:
        candidates = candidates[:limit]

    log.info(
        "Migration plan: {} to migrate, {} already done",
        len(candidates),
        len(result.skipped),
    )

    for md_file in candidates:
        video_id = md_file.stem
        parsed = _parse_old_transcript(md_file)
        if not parsed:
            log.warning("Could not parse frontmatter: {}", md_file)
            result.failed.append(video_id)
            continue

        if dry_run:
            log.info("DRY RUN: would migrate {} - {}", video_id, parsed["title"][:60])
            result.migrated.append(video_id)
            continue

        # Fetch metadata from yt-dlp
        meta = _fetch_metadata_ytdlp(video_id)
        if meta:
            upload_date = meta["upload_date"]
            duration = meta["duration_seconds"]
            view_count = meta["view_count"]
            thumbnail = meta["thumbnail_url"]
            if verbose:
                log.info("[meta ok] {} upload_date={}", video_id, upload_date)
        else:
            log.warning("[meta fail] {} — using fallback values", video_id)
            upload_date = ""
            duration = 0
            view_count = 0
            thumbnail = ""

        video = YouTubeVideo(
            video_id=parsed["video_id"],
            title=parsed["title"],
            channel=parsed["channel"],
            published_at=upload_date,
            transcript_text=parsed["transcript"],
            duration_seconds=duration,
            thumbnail_url=thumbnail,
            view_count=view_count,
        )

        try:
            inbox_dir = paths.connector_inbox("youtube")
            _write_issue(inbox_dir, video, parsed["transcript"], parsed["language"])
            _write_source_state(paths, f"youtube:{video_id}", video, "inbox")
            result.migrated.append(video_id)
            if verbose:
                log.info(
                    "[migrated] {} - {} ({})",
                    video_id,
                    parsed["title"][:60],
                    _upload_date_to_display(upload_date),
                )
        except Exception as exc:  # noqa: BLE001
            log.error("[FAIL] {}: {}", video_id, exc)
            result.failed.append(video_id)
            continue

        if cleanup:
            md_file.unlink()
            result.cleaned_up.append(video_id)
            if verbose:
                log.info("[cleanup] removed {}", md_file)

    return result


def _new_format_exists(paths: Paths, video_id: str) -> bool:
    """Return True if a new-format inbox folder exists for this video ID."""
    inbox = paths.connector_inbox("youtube")
    if not inbox.is_dir():
        return False
    for folder in inbox.iterdir():
        if folder.is_dir() and folder.name.endswith(f"--{video_id}"):
            return True
    return False
