"""Tests for the YouTube sync module (Sprint 4)."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cogforge.sync_youtube import (
    YouTubeSyncResult,
    YouTubeVideo,
    _build_issue_dir,
    _extract_video_id,
    _format_duration,
    _language_match,
    _parse_metadata,
    _transcript_to_markdown,
    _write_issue,
    sync_youtube,
)


class TestYouTubeVideo:
    def test_minimal(self):
        video = YouTubeVideo(video_id="dQw4w9WgXcQ", title="Test", channel="TestChannel")
        assert video.video_id == "dQw4w9WgXcQ"
        assert video.title == "Test"
        assert video.channel == "TestChannel"
        assert video.transcript_text == ""
        assert video.available_languages == []
        assert video.duration_seconds == 0

    def test_full(self):
        video = YouTubeVideo(
            video_id="dQw4w9WgXcQ",
            title="Full Video",
            channel="FullChannel",
            published_at="20260514",
            transcript_text="Hello world",
            available_languages=["en", "fr"],
            duration_seconds=212,
            thumbnail_url="https://example.com/thumb.jpg",
            view_count=1234567,
        )
        assert video.duration_seconds == 212
        assert video.view_count == 1234567
        assert video.available_languages == ["en", "fr"]

    def test_canonical_url(self):
        video = YouTubeVideo(video_id="dQw4w9WgXcQ", title="T", channel="C")
        assert video.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_date_display_full(self):
        video = YouTubeVideo(video_id="dQw4w9WgXcQ", title="T", channel="C",
                             published_at="20260514")
        assert video.date_display == "2026-05-14"

    def test_date_display_short(self):
        video = YouTubeVideo(video_id="dQw4w9WgXcQ", title="T", channel="C",
                             published_at="2026")
        assert video.date_display == "2026"

    def test_date_display_empty(self):
        video = YouTubeVideo(video_id="dQw4w9WgXcQ", title="T", channel="C",
                             published_at="")
        assert video.date_display == ""


class TestYouTubeSyncResult:
    def test_default(self):
        result = YouTubeSyncResult(source_id="test")
        assert result.source_id == "test"
        assert result.connector == "youtube"
        assert result.new_count == 0
        assert result.source_ids == []

    def test_with_values(self):
        result = YouTubeSyncResult(
            source_id="test",
            new_count=5, skipped_count=3, error_count=1,
            total_discovered=10, source_ids=["a", "b"], errors=["err1"],
        )
        assert result.new_count == 5
        assert result.error_count == 1
        assert result.total_discovered == 10


class TestExtractVideoId:
    def test_standard_url(self):
        assert _extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self):
        assert _extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self):
        assert _extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_url_with_params(self):
        assert _extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30") == "dQw4w9WgXcQ"

    def test_invalid_url(self):
        assert _extract_video_id("https://www.google.com") is None

    def test_empty_string(self):
        assert _extract_video_id("") is None


class TestParseMetadata:
    def test_valid(self):
        raw = {
            "id": "dQw4w9WgXcQ",
            "title": "Test Video",
            "channel": "TestChannel",
            "upload_date": "20260514",
            "duration": 212,
            "thumbnail": "https://example.com/thumb.jpg",
            "view_count": 1234567,
        }
        video = _parse_metadata(raw)
        assert video is not None
        assert video.video_id == "dQw4w9WgXcQ"
        assert video.title == "Test Video"
        assert video.channel == "TestChannel"
        assert video.published_at == "20260514"
        assert video.duration_seconds == 212
        assert video.view_count == 1234567

    def test_uses_uploader_fallback(self):
        raw = {"id": "abc", "title": "T", "uploader": "UploaderName"}
        video = _parse_metadata(raw)
        assert video is not None
        assert video.channel == "UploaderName"

    def test_none_handling(self):
        assert _parse_metadata({}) is None
        assert _parse_metadata(None) is None  # type: ignore[arg-type]

    def test_handles_zero_values(self):
        raw = {"id": "abc", "title": "T", "duration": 0, "view_count": 0}
        video = _parse_metadata(raw)
        assert video is not None
        assert video.duration_seconds == 0


class TestFormatDuration:
    def test_zero(self):
        assert _format_duration(0) == "0:00"

    def test_seconds_only(self):
        assert _format_duration(59) == "0:59"

    def test_minutes_and_seconds(self):
        assert _format_duration(212) == "3:32"

    def test_hours(self):
        assert _format_duration(3723) == "1:02:03"


class TestLanguageMatch:
    def test_exact_match(self):
        assert _language_match(["en", "fr"], ["fr", "de"]) == "fr"

    def test_fallback_to_base(self):
        assert _language_match(["en-US"], ["en"]) == "en"

    def test_no_match(self):
        assert _language_match(["zh"], ["en", "fr"]) is None

    def test_first_preferred_wins(self):
        assert _language_match(["en", "fr"], ["fr", "en"]) == "en"


class TestTranscriptToMarkdown:
    def test_basic(self):
        video = YouTubeVideo(
            video_id="dQw4w9WgXcQ", title="Test Video", channel="TestChannel",
            published_at="20260514", duration_seconds=212, view_count=1234,
        )
        md = _transcript_to_markdown(video, "This is the transcript.")
        assert "# Test Video" in md
        assert "**Channel:** TestChannel" in md
        assert "**Published:** 2026-05-14" in md
        assert "**Duration:** 3:32" in md
        assert "**Views:** 1,234" in md
        assert "**Video ID:** dQw4w9WgXcQ" in md
        assert "youtube.com/watch?v=dQw4w9WgXcQ" in md
        assert "This is the transcript." in md

    def test_no_transcript(self):
        video = YouTubeVideo(
            video_id="dQw4w9WgXcQ", title="T", channel="C",
            published_at="20260514",
        )
        md = _transcript_to_markdown(video, "")
        assert "No transcript available" in md


class TestBuildIssueDir:
    def test_with_date(self, tmp_path):
        video = YouTubeVideo(
            video_id="dQw4w9WgXcQ", title="My Video", channel="C",
            published_at="20260514",
        )
        result = _build_issue_dir(tmp_path, video)
        assert result.parent == tmp_path
        assert "2026-05-14" in result.name
        assert "dQw4w9WgXcQ" in result.name
        assert "my-video" in result.name

    def test_no_date(self, tmp_path):
        video = YouTubeVideo(
            video_id="dQw4w9WgXcQ", title="My Video", channel="C",
        )
        result = _build_issue_dir(tmp_path, video)
        assert "0000-00-00" in result.name

    def test_special_chars_sanitized(self, tmp_path):
        video = YouTubeVideo(
            video_id="dQw4w9WgXcQ", title="My: Special! Video@2024", channel="C",
            published_at="20260514",
        )
        result = _build_issue_dir(tmp_path, video)
        assert ":" not in result.name
        assert "!" not in result.name
        assert "@" not in result.name


class TestWriteIssue:
    def test_creates_files(self, tmp_path):
        video = YouTubeVideo(
            video_id="dQw4w9WgXcQ", title="Test Video", channel="TestChannel",
            published_at="20260514", duration_seconds=212, view_count=1234,
        )
        result = _write_issue(tmp_path, video, "Hello transcript.", "en")
        assert (result / "index.md").exists()
        assert (result / "original.json").exists()

        md_content = (result / "index.md").read_text()
        assert "Test Video" in md_content
        assert "Hello transcript." in md_content
        assert "---" in md_content

        json_content = json.loads((result / "original.json").read_text())
        assert json_content["video_id"] == "dQw4w9WgXcQ"
        assert json_content["transcript_language"] == "en"


class TestSyncYouTubeDryRun:
    def test_dry_run_single_video_id(self, tmp_path):
        state_dir = tmp_path / ".llmkb" / "state" / "sources"
        state_dir.mkdir(parents=True, exist_ok=True)
        inbox_dir = tmp_path / "inbox" / "youtube"
        inbox_dir.mkdir(parents=True, exist_ok=True)

        cfg = MagicMock()
        cfg.sources = {}

        paths = MagicMock()
        paths.state_sources = state_dir
        paths.connector_inbox.return_value = inbox_dir

        with patch("cogforge.sync_youtube._fetch_video_metadata", return_value=({}, "")):
            result = sync_youtube(
                source_id=None,
                all_sources=False,
                config=cfg,
                paths=paths,
                video_id="dQw4w9WgXcQ",
                dry_run=True,
            )

        assert result.total_discovered == 1
        assert result.new_count == 0
        assert len(result.source_ids) == 1
        assert "youtube:dQw4w9WgXcQ" in result.source_ids

    def test_dry_run_no_videos(self, tmp_path):
        state_dir = tmp_path / ".llmkb" / "state" / "sources"
        state_dir.mkdir(parents=True, exist_ok=True)

        cfg = MagicMock()
        cfg.sources = {}

        paths = MagicMock()
        paths.state_sources = state_dir

        result = sync_youtube(
            source_id=None,
            all_sources=False,
            config=cfg,
            paths=paths,
            dry_run=True,
        )

        assert result.total_discovered == 0
        assert len(result.errors) == 1

    def test_dry_run_extracts_url(self, tmp_path):
        state_dir = tmp_path / ".llmkb" / "state" / "sources"
        state_dir.mkdir(parents=True, exist_ok=True)

        cfg = MagicMock()
        cfg.sources = {}

        paths = MagicMock()
        paths.state_sources = state_dir

        result = sync_youtube(
            source_id=None,
            all_sources=False,
            config=cfg,
            paths=paths,
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            dry_run=True,
        )

        assert result.total_discovered == 1

    def test_dry_run_bad_url(self, tmp_path):
        state_dir = tmp_path / ".llmkb" / "state" / "sources"
        state_dir.mkdir(parents=True, exist_ok=True)

        cfg = MagicMock()
        cfg.sources = {}

        paths = MagicMock()
        paths.state_sources = state_dir

        result = sync_youtube(
            source_id=None,
            all_sources=False,
            config=cfg,
            paths=paths,
            url="https://www.google.com",
            dry_run=True,
        )

        assert result.total_discovered == 0
        assert len(result.errors) == 1


class TestYouTubeSyncResultJSON:
    def test_sync_result_is_json_serializable(self):
        result = YouTubeSyncResult(
            source_id="test", new_count=5, source_ids=["a", "b"], errors=["err1"],
        )
        data = {
            "connector": result.connector,
            "total_discovered": result.total_discovered,
            "new_count": result.new_count,
            "skipped_count": result.skipped_count,
            "error_count": result.error_count,
            "source_ids": result.source_ids,
            "errors": result.errors,
        }
        json.dumps(data)


class TestCLIIntegration:
    def test_sync_youtube_help(self):
        from click.testing import CliRunner
        from cogforge.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["sync", "youtube", "--help"])
        assert result.exit_code == 0
        assert "--source-id" in result.output
        assert "--all" in result.output
        assert "--url" in result.output
        assert "--video-id" in result.output
        assert "--max" in result.output
        assert "--include-failed" in result.output

    def test_sync_help_includes_youtube(self):
        from click.testing import CliRunner
        from cogforge.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["sync", "--help"])
        assert result.exit_code == 0
        assert "youtube" in result.output
