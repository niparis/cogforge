"""Tests for the Apple Notes sync module (Sprint 5)."""
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cogforge.sync_apple_notes import (
    AppleNotesSyncResult,
    NoteRow,
    _html_to_markdown,
    _sanitize_filename,
    sync_apple_notes,
)


class TestAppleNotesSyncResult:
    def test_defaults(self):
        result = AppleNotesSyncResult()
        assert result.connector == "apple-notes"
        assert result.new_count == 0
        assert result.skipped_count == 0
        assert result.errors == []

    def test_with_values(self):
        result = AppleNotesSyncResult(
            new_count=5, skipped_count=2, error_count=1,
            total_discovered=10, source_ids=["a", "b"],
            errors=["err1"],
        )
        assert result.new_count == 5
        assert result.total_discovered == 10
        assert len(result.errors) == 1

    def test_json_serializable(self):
        result = AppleNotesSyncResult(
            new_count=3, source_ids=["a", "b"], errors=["e"]
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
        assert json.dumps(data)


class TestNoteRow:
    def test_creation(self):
        note = NoteRow(pk=42, identifier="abc-123", title="Test Note")
        assert note.pk == 42
        assert note.identifier == "abc-123"
        assert note.title == "Test Note"


class TestSanitizeFilename:
    def test_normal(self):
        assert _sanitize_filename("My Note") == "My Note"

    def test_path_separators(self):
        result = _sanitize_filename("note/with/slashes")
        assert "/" not in result
        assert "\\" not in result

    def test_colon(self):
        result = _sanitize_filename("note:with:colons")
        assert ":" not in result

    def test_empty(self):
        assert _sanitize_filename("") == "untitled"

    def test_whitespace_only(self):
        assert _sanitize_filename("   ") == "untitled"

    def test_very_long(self):
        long_name = "a" * 300
        result = _sanitize_filename(long_name)
        assert len(result) <= 200

    def test_null_byte(self):
        result = _sanitize_filename("note\x00with\x00null")
        assert "\x00" not in result


class TestHtmlToMarkdown:
    def test_basic(self):
        html = "<h1>My Note</h1><p>Content here.</p>"
        md = _html_to_markdown(html, "My Note")
        assert "# My Note" in md
        assert "Content here." in md

    def test_removes_duplicate_title(self):
        """First line matching the title as # heading is stripped."""
        html = "# My Note\n\nextra content"
        md = _html_to_markdown(html, "My Note")
        # Title should not be duplicated
        lines = md.splitlines()
        title_count = sum(1 for l in lines if l.strip() == "# My Note")
        assert title_count == 1


class TestTokenLinkRegex:
    def test_extracts_uuid(self):
        from cogforge.sync_apple_notes import TOKEN_LINK_RE

        text = "applenotes:note/ABC123-DEF456-789"
        m = TOKEN_LINK_RE.search(text)
        assert m is not None
        assert m.group(1) == "ABC123-DEF456-789"

    def test_case_insensitive(self):
        from cogforge.sync_apple_notes import TOKEN_LINK_RE

        text = "AppleNotes:note/a1b2c3d4-e5f6-7890?ownerIdentifier=..."
        m = TOKEN_LINK_RE.search(text)
        assert m is not None
        assert m.group(1) == "a1b2c3d4-e5f6-7890"


class TestSyncAppleNotesDryRun:
    def test_dry_run_no_sources(self, tmp_path):
        state_dir = tmp_path / ".llmkb" / "state" / "sources"
        state_dir.mkdir(parents=True, exist_ok=True)

        cfg = MagicMock()
        cfg.sources = {}

        paths = MagicMock()
        paths.state_sources = state_dir

        result = sync_apple_notes(
            paths=paths,
            config=cfg,
            dry_run=True,
        )

        assert result.total_discovered == 0
        assert len(result.errors) == 1

    def test_dry_run_with_root_title(self, tmp_path):
        state_dir = tmp_path / ".llmkb" / "state" / "sources"
        state_dir.mkdir(parents=True, exist_ok=True)

        cfg = MagicMock()
        cfg.sources = {}

        paths = MagicMock()
        paths.state_sources = state_dir

        # We expect this to raise because the Notes DB doesn't exist,
        # but since we're in a test environment, we mock the DB functions
        with patch("cogforge.sync_apple_notes._open_db") as mock_db:
            mock_conn = MagicMock()
            mock_db.return_value = mock_conn

            with patch("cogforge.sync_apple_notes._entity_ids") as mock_ent:
                mock_ent.return_value = {"ICNote": 1, "ICInlineAttachment": 2}
                with patch("cogforge.sync_apple_notes._detect_columns") as mock_col:
                    mock_col.return_value = {"note_account_fk": "ZACCOUNT1"}
                    with patch("cogforge.sync_apple_notes._discover_store_uuid") as mock_uuid:
                        mock_uuid.return_value = "test-store-uuid"
                        with patch("cogforge.sync_apple_notes._find_starting_note") as mock_find:
                            mock_find.return_value = NoteRow(
                                pk=1, identifier="test-123", title="Test Note"
                            )

                            result = sync_apple_notes(
                                paths=paths,
                                config=cfg,
                                root_title="Test Note",
                                dry_run=True,
                            )

                            assert result.total_discovered == 1
                            assert len(result.source_ids) == 1
                            assert result.source_ids[0] == "apple-notes:test-123"
                            assert result.new_count == 0


class TestCLIIntegration:
    def test_sync_apple_notes_help(self):
        from click.testing import CliRunner
        from cogforge.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["sync", "apple-notes", "--help"])
        assert result.exit_code == 0
        assert "--source-id" in result.output
        assert "--all" in result.output
        assert "--root-title" in result.output
        assert "--max-depth" in result.output

    def test_sync_help_includes_apple_notes(self):
        from click.testing import CliRunner
        from cogforge.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["sync", "--help"])
        assert result.exit_code == 0
        assert "apple-notes" in result.output
