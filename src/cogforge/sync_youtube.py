"""YouTube connector: sync, fetch, parse, write."""
from __future__ import annotations

import json
from loguru import logger as log
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cogforge.paths import Paths
from cogforge.state import (
    ContentInfo,
    LastError,
    Origin,
    RunsInfo,
    SourcePaths,
    SourceState,
    SourceStatus,
    load_state,
    save_state,
)



SLEEP_BETWEEN_VIDEOS = 3.0  # seconds between transcript requests to avoid IP bans


# ── YouTube Video Metadata ─────────────────────────────────────────────────────

@dataclass
class YouTubeVideo:
    video_id: str
    title: str
    channel: str
    published_at: str = ""  # YYYYMMDD from yt-dlp
    transcript_text: str = ""
    available_languages: list[str] = field(default_factory=list)
    duration_seconds: int = 0
    thumbnail_url: str = ""
    view_count: int = 0

    @property
    def canonical_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def date_display(self) -> str:
        if len(self.published_at) >= 8:
            d = self.published_at[:8]
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        return self.published_at


# ── Language matching ─────────────────────────────────────────────────────────

def _language_match(preferred: list[str], available: list[str]) -> str | None:
    """Return best matching language code from available list based on preferences."""
    for pref in preferred:
        if pref in available:
            return pref
    for pref in preferred:
        base = pref.split("-")[0]
        if base in available:
            return base
    return None


# ── Metadata fetching ──────────────────────────────────────────────────────────

def _fetch_video_metadata(video_id: str) -> tuple[dict[str, Any], str]:
    """Fetch video metadata via yt-dlp JSON output.

    Returns (metadata_dict, error_message). On success, error_message is empty.
    On failure, metadata_dict is empty and error_message describes what went wrong.
    """
    import subprocess

    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--dump-json",
                "--no-download",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            log.warning("yt-dlp failed for {}: {}", video_id, err)
            return {}, err
        return json.loads(result.stdout), ""
    except FileNotFoundError:
        return {}, "yt-dlp not found in PATH"
    except json.JSONDecodeError as e:
        log.warning("yt-dlp invalid JSON for {}: {}", video_id, e)
        return {}, str(e)
    except subprocess.TimeoutExpired:
        return {}, "yt-dlp timed out"


def _fetch_playlist_videos(playlist_id: str) -> list[str]:
    """Fetch video IDs from a YouTube playlist using yt-dlp."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--flat-playlist",
                "--dump-json",
                f"https://www.youtube.com/playlist?list={playlist_id}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            log.warning("yt-dlp playlist failed: {}", result.stderr.strip())
            return []

        video_ids = []
        for line in result.stdout.strip().splitlines():
            if line.strip():
                try:
                    entry = json.loads(line)
                    if "id" in entry:
                        video_ids.append(entry["id"])
                except json.JSONDecodeError:
                    continue
        return video_ids
    except FileNotFoundError:
        log.error("yt-dlp not found in PATH")
        return []
    except subprocess.TimeoutExpired:
        log.warning("yt-dlp playlist fetch timed out")
        return []


def _fetch_transcript(
    video_id: str,
    preferred_languages: list[str] | None = None,
) -> tuple[str, str, list[str]]:
    """Fetch transcript for a video. Returns (text, language_code, available_languages)."""
    from youtube_transcript_api import YouTubeTranscriptApi

    preferred = preferred_languages or ["en"]
    available: list[str] = []

    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)
        available = [t.language_code for t in transcript_list]

        lang = _language_match(preferred, available)
        if not lang:
            lang = "en" if "en" in available else (available[0] if available else "")

        if not lang:
            return "", "", available

        transcript = transcript_list.find_transcript([lang])
        parts = transcript.fetch()
        text = " ".join(p.text for p in parts)
        return text, lang, available

    except Exception as e:
        err_str = str(e)
        if _is_rate_limited(err_str):
            log.warning("RATE LIMITED on {}: {}", video_id, err_str)
            raise  # re-raise to let orchestrator stop the batch
        log.warning("transcript fetch failed for {}: {}", video_id, err_str)
        return "", "", available


def _download_audio(video_id: str, out_dir: Path) -> Path | None:
    """Download audio as MP3 via yt-dlp. Returns path to audio.mp3 or None on failure."""
    import subprocess

    output_template = str(out_dir / "audio.%(ext)s")
    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "5",
                "--no-playlist",
                "--output", output_template,
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            log.warning("audio download failed for {}: {}", video_id, result.stderr.strip()[:200])
            return None
        audio_file = out_dir / "audio.mp3"
        return audio_file if audio_file.exists() else None
    except subprocess.TimeoutExpired:
        log.warning("audio download timed out for {}", video_id)
        return None
    except FileNotFoundError:
        log.error("yt-dlp not found in PATH")
        return None


def _is_rate_limited(error_msg: str) -> bool:
    """Return True if the error indicates YouTube is blocking/rate-limiting requests."""
    patterns = [
        r"YouTube is blocking",
        r"blocked by YouTube",
        r"too many requests",
    ]
    for pattern in patterns:
        if re.search(pattern, error_msg, re.IGNORECASE):
            return True
    return False


# ── Parsing and writing ────────────────────────────────────────────────────────

def _parse_metadata(raw: dict[str, Any]) -> YouTubeVideo | None:
    """Parse raw yt-dlp JSON into a YouTubeVideo."""
    if not raw or "id" not in raw:
        return None

    return YouTubeVideo(
        video_id=raw["id"],
        title=raw.get("title", ""),
        channel=raw.get("channel", raw.get("uploader", "")),
        published_at=raw.get("upload_date", ""),
        duration_seconds=raw.get("duration", 0) or 0,
        thumbnail_url=raw.get("thumbnail", ""),
        view_count=raw.get("view_count", 0) or 0,
    )


def _format_duration(seconds: int) -> str:
    """Format duration in seconds as HH:MM:SS."""
    if seconds <= 0:
        return "0:00"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _transcript_to_markdown(video: YouTubeVideo, transcript_text: str) -> str:
    """Format video info and transcript into Markdown."""
    lines = [
        f"# {video.title}",
        "",
        f"**Channel:** {video.channel}",
        f"**Published:** {video.date_display}",
        f"**Duration:** {_format_duration(video.duration_seconds)}",
        f"**Views:** {video.view_count:,}",
        f"**Video ID:** {video.video_id}",
        f"**URL:** {video.canonical_url}",
        "",
        "---",
        "",
        transcript_text if transcript_text else "_No transcript available. Audio downloaded for transcription._",
    ]
    return "\n".join(lines)


def _build_issue_dir(out_dir: Path, video: YouTubeVideo) -> Path:
    """Get or create the issue directory for a video."""
    date_prefix = video.date_display or "0000-00-00"
    slug = re.sub(r"[^\w\s-]", "", video.title.lower())[:60].strip().replace(" ", "-")
    dirname = f"{date_prefix}-{slug}--{video.video_id}"
    folder = out_dir / dirname
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _write_issue(
    out_dir: Path,
    video: YouTubeVideo,
    transcript_text: str,
    language: str,
    audio_file: Path | None = None,
) -> Path:
    """Write index.md and original.json into the issue folder. Returns folder path."""
    from datetime import date

    import yaml

    folder = _build_issue_dir(out_dir, video)

    frontmatter: dict[str, Any] = {
        "source": video.canonical_url,
        "connector": "youtube",
        "title": video.title,
        "author": video.channel,
        "date_published": video.date_display,
        "date_fetched": date.today().isoformat(),
        "slug": video.video_id,
        "language": language,
        "duration_seconds": video.duration_seconds,
        "view_count": video.view_count,
    }
    if audio_file is not None:
        frontmatter["has_audio"] = True

    fm = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    body_md = _transcript_to_markdown(video, transcript_text)
    full_md = f"---\n{fm}\n---\n\n{body_md}\n"

    (folder / "index.md").write_text(full_md, encoding="utf-8")
    (folder / "original.json").write_text(
        json.dumps(
            {
                "video_id": video.video_id,
                "title": video.title,
                "channel": video.channel,
                "published_at": video.published_at,
                "duration_seconds": video.duration_seconds,
                "view_count": video.view_count,
                "thumbnail_url": video.thumbnail_url,
                "transcript_language": language,
                "has_audio": audio_file is not None,
                "audio_file": audio_file.name if audio_file is not None else None,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return folder


# ── Sync Result ────────────────────────────────────────────────────────────────

@dataclass
class YouTubeSyncResult:
    """Result of a YouTube sync operation."""

    source_id: str
    connector: str = "youtube"
    new_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    total_discovered: int = 0
    source_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ── Source state writing ──────────────────────────────────────────────────────


def _write_source_state(
    paths: Paths,
    source_id: str,
    video: YouTubeVideo | None,
    status: str,
    *,
    error: str | None = None,
) -> None:
    """Write source state YAML after sync."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    origin = Origin(
        url=video.canonical_url if video else None,
        title=video.title if video else None,
        external_id=video.video_id if video else None,
        fetched_at=now,
    )

    issue_dirname_val = None
    if video:
        issue_dirname_val = _build_issue_dir(paths.connector_inbox("youtube"), video).name

    state = SourceState(
        version=1,
        id=source_id,
        connector="youtube",
        status=status,
        origin=origin,
        content=ContentInfo(
            estimated_chars=len(video.transcript_text)
            if video and video.transcript_text
            else None
        ),
        paths=SourcePaths(
            inbox=f"inbox/youtube/{issue_dirname_val}" if issue_dirname_val else None
        ),
        runs=RunsInfo(last_sync=now),
        last_error=LastError(
            phase="sync",
            message=error,
            retryable=True,
            occurred_at=now,
        )
        if error
        else LastError(),
    )
    save_state(paths.state_sources, state)


# ── Sync Orchestration ────────────────────────────────────────────────────────


def sync_youtube(
    source_id: str | None,
    all_sources: bool,
    config: Any,
    paths: Paths,
    *,
    url: str | None = None,
    video_id: str | None = None,
    max_videos: int | None = None,
    include_failed: bool = False,
    preferred_languages: list[str] | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> YouTubeSyncResult:
    """Sync configured YouTube sources into the wiki inbox."""
    from cogforge.config import Config

    if not isinstance(config, Config):
        config = Config()

    result = YouTubeSyncResult(source_id=source_id or "")

    # Collect video IDs to sync
    video_ids_to_sync: list[str] = []

    # Case 1: Explicit video URL or video ID (single video, no config needed)
    if url or video_id:
        vid = video_id or _extract_video_id(url)  # type: ignore[arg-type]
        if vid:
            video_ids_to_sync.append(vid)
        else:
            result.errors.append(f"Could not extract video ID from: {url}")
            return result

    # Case 2: All configured YouTube sources
    elif all_sources:
        for src in config.sources.get("youtube", []):
            if not src.id or not src.enabled:
                continue
            if source_id and src.id != source_id:
                continue
            if src.playlist_id:
                discovered = _fetch_playlist_videos(src.playlist_id)
                if verbose:
                    log.info(
                        "source={} playlist={} discovered={}",
                        src.id,
                        src.playlist_id,
                        len(discovered),
                    )
                video_ids_to_sync.extend(discovered)
            else:
                video_ids_to_sync.append(src.id)

    # Case 3: Single source_id from config
    elif source_id:
        youtube_sources = config.sources.get("youtube", [])
        found = False
        for src in youtube_sources:
            if src.id == source_id and src.enabled:
                found = True
                if src.playlist_id:
                    discovered = _fetch_playlist_videos(src.playlist_id)
                    video_ids_to_sync.extend(discovered)
                else:
                    video_ids_to_sync.append(src.id)
                break
        if not found:
            video_ids_to_sync.append(source_id)

    if not video_ids_to_sync:
        log.warning("No video IDs to sync")
        result.errors.append("No video IDs to sync")
        return result

    result.total_discovered = len(video_ids_to_sync)
    if verbose:
        log.info("Total videos to process: {}", len(video_ids_to_sync))

    if dry_run:
        limit = max_videos or len(video_ids_to_sync)
        for vid in video_ids_to_sync[:limit]:
            log.info("DRY RUN: would sync video {}", vid)
        result.source_ids = [f"youtube:{vid}" for vid in video_ids_to_sync[:limit]]
        return result

    # Build set of already-synced video IDs (checks new + old format on disk)
    synced_ids = _build_synced_ids(paths)
    if verbose:
        log.info("Already synced on disk: {} videos", len(synced_ids))

    # Process each video
    new_count = 0
    skipped = 0
    errors = 0
    rate_limited = False

    for vid in video_ids_to_sync:
        if rate_limited or (max_videos is not None and new_count >= max_videos):
            break

        v_source_id = f"youtube:{vid}"

        existing_state = load_state(paths.state_sources, v_source_id)
        if existing_state and existing_state.status == SourceStatus.PROCESSED.value:
            skipped += 1
            if verbose:
                log.info("Skipping already-processed (state): {}", vid)
            continue

        if (
            existing_state
            and existing_state.status == SourceStatus.FAILED.value
            and not include_failed
        ):
            skipped += 1
            if verbose:
                log.info("Skipping failed video (use --include-failed): {}", vid)
            continue

        # Check file existence (catches old-script syncs without state files)
        if _already_synced_on_disk(paths, vid, synced_ids):
            skipped += 1
            if verbose:
                log.info("Skipping already-synced (file on disk): {}", vid)
            continue

        try:
            raw_meta, meta_error = _fetch_video_metadata(vid)
            video = _parse_metadata(raw_meta)

            if video is None:
                is_permanent = _is_permanent_failure(meta_error)
                status = "excluded" if is_permanent else "failed"
                err_msg = meta_error or "Metadata fetch failed"
                errors += 1
                result.errors.append(f"{vid}: {err_msg}")
                _write_source_state(
                    paths, v_source_id, None, status, error=err_msg
                )
                continue

            transcript_text, lang, avail_langs = _fetch_transcript(
                vid, preferred_languages
            )
            video.available_languages = avail_langs

            # Fallback to English auto-generated if preferred lang had no match
            if (
                not transcript_text
                and preferred_languages
                and "en" in preferred_languages
            ):
                transcript_text, lang, avail_langs = _fetch_transcript(vid, ["en"])
                video.available_languages = avail_langs or video.available_languages

            out_dir = paths.connector_inbox("youtube")
            if transcript_text:
                folder = _write_issue(out_dir, video, transcript_text, lang)
                _write_source_state(paths, v_source_id, video, "inbox")
                result.source_ids.append(v_source_id)
                new_count += 1
                if verbose:
                    log.info("[NEW] {} - {} ({})", vid, video.title[:60], lang)

            elif video.duration_seconds > 0:
                # No transcript — try audio fallback
                folder = _build_issue_dir(out_dir, video)
                audio_path = _download_audio(vid, folder)
                _write_issue(out_dir, video, "", "", audio_file=audio_path)
                if audio_path:
                    _write_source_state(paths, v_source_id, video, SourceStatus.AUDIO_ONLY.value)
                    result.source_ids.append(v_source_id)
                    new_count += 1
                    if verbose:
                        log.info("[AUDIO] {} - {}", vid, video.title[:60])
                else:
                    _write_source_state(
                        paths, v_source_id, video, "excluded",
                        error="No transcript, audio download failed",
                    )
                    result.errors.append(f"{vid}: no transcript, audio download failed (excluded)")
                    errors += 1

            else:
                _write_source_state(
                    paths, v_source_id, video, "excluded",
                    error="No transcript available",
                )
                result.errors.append(f"{vid}: no transcript available (excluded)")
                errors += 1

        except Exception as e:  # noqa: BLE001
            err_str = str(e)
            if _is_rate_limited(err_str):
                log.warning("RATE LIMITED — stopping batch. {} remaining.", len(video_ids_to_sync) - new_count - skipped - errors)
                result.errors.append(f"{vid}: RATE LIMITED — {err_str}")
                errors += 1
                rate_limited = True
                break

            log.error("[FAIL] {}: {}", vid, e)
            result.errors.append(f"{vid}: {e}")
            _write_source_state(
                paths, f"youtube:{vid}", None, "failed", error=str(e)
            )
            errors += 1

        # Sleep between videos to avoid IP bans (only after actual API calls, not skips)
        if not existing_state or existing_state.status not in (SourceStatus.PROCESSED.value, SourceStatus.FAILED.value):
            time.sleep(SLEEP_BETWEEN_VIDEOS)
        elif include_failed and existing_state and existing_state.status == SourceStatus.FAILED.value:
            time.sleep(SLEEP_BETWEEN_VIDEOS)

    result.new_count = new_count
    result.skipped_count = skipped
    result.error_count = errors
    log.info(
        "done. new={} skipped={} errors={} total={}",
        new_count,
        skipped,
        errors,
        len(video_ids_to_sync),
    )
    return result


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from a URL."""
    m = re.search(r"(?:v=|youtu\.be/|embed/|watch\?v=)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def _is_permanent_failure(error_msg: str) -> bool:
    """Return True if the yt-dlp error indicates a permanent (non-retryable) failure."""
    permanent_patterns = [
        r"video has been removed",
        r"Private video",
        r"This video is private",
        r"This video is unavailable",
        r"Video unavailable",
    ]
    for pattern in permanent_patterns:
        if re.search(pattern, error_msg, re.IGNORECASE):
            return True
    return False


def _already_synced_on_disk(paths: Paths, video_id: str, synced_ids: set[str] | None = None) -> bool:
    """Check if a video has already been synced to disk.

    If synced_ids is provided, uses that precomputed set.
    Otherwise scans disk directly (one-off check).
    """
    if synced_ids is not None:
        return video_id in synced_ids

    for base in (paths.connector_inbox("youtube"), paths.connector_raw("youtube")):
        if base.is_dir():
            for folder in base.iterdir():
                if folder.is_dir() and video_id in folder.name:
                    if (folder / "index.md").exists():
                        return True

    for base in (paths.root / "inbox" / "transcripts", paths.root / "raw" / "transcripts"):
        candidate = base / f"{video_id}.md"
        if candidate.exists():
            return True

    return False


def _build_synced_ids(paths: Paths) -> set[str]:
    """Build set of video IDs already synced to disk (new + old formats)."""
    synced: set[str] = set()

    # New format: folders under inbox/youtube/ and raw/youtube/
    for base in (paths.connector_inbox("youtube"), paths.connector_raw("youtube")):
        if base.is_dir():
            for folder in base.iterdir():
                if folder.is_dir() and (folder / "index.md").exists():
                    vid = _extract_video_id_from_dirname(folder.name)
                    if vid:
                        synced.add(vid)

    # Old format: flat .md files
    for base in (paths.root / "inbox" / "transcripts", paths.root / "raw" / "transcripts"):
        if base.is_dir():
            for md_file in base.glob("*.md"):
                synced.add(md_file.stem)

    return synced


def _extract_video_id_from_dirname(dirname: str) -> str | None:
    """Extract 11-char YouTube video ID from folder name (format: date-slug--VID)."""
    m = re.search(r"--([A-Za-z0-9_-]{11})$", dirname)
    if m:
        return m.group(1)
    return None
