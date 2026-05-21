"""Tests for path resolution utilities."""
import pytest
from pathlib import Path

from cogforge.paths import Paths, _encode_source_id, _decode_source_id, resolve_wiki_root


class TestResolveWikiRoot:
    def test_resolve_from_repo_root(self, tmp_path: Path) -> None:
        wiki = tmp_path / "llm_wiki"
        wiki.mkdir()
        result = resolve_wiki_root(wiki)
        assert result == wiki

    def test_resolve_from_subdirectory(self, tmp_path: Path) -> None:
        wiki = tmp_path / "llm_wiki"
        wiki.mkdir()
        deep = wiki / "inbox" / "youtube"
        deep.mkdir(parents=True)
        result = resolve_wiki_root(deep)
        assert result == wiki

    def test_resolve_from_nonexistent(self, tmp_path: Path) -> None:
        deep = tmp_path / "some" / "deep" / "path"
        deep.mkdir(parents=True)
        result = resolve_wiki_root(deep)
        assert result == deep / "llm_wiki"


class TestPaths:
    def test_basic_paths(self, tmp_path: Path) -> None:
        p = Paths(tmp_path)
        assert p.inbox == tmp_path / "inbox"
        assert p.raw == tmp_path / "raw"
        assert p.wiki == tmp_path / "wiki"
        assert p.history == tmp_path / "history"

    def test_nested_paths(self, tmp_path: Path) -> None:
        p = Paths(tmp_path)
        assert p.connector_inbox("youtube") == tmp_path / "inbox" / "youtube"
        assert p.connector_raw("substack") == tmp_path / "raw" / "substack"
        assert p.connector_pageindex("youtube", "abc") == tmp_path / "pageindex" / "youtube" / "abc"

    def test_state_file(self, tmp_path: Path) -> None:
        p = Paths(tmp_path)
        assert p.state_file("youtube:TIYnaNaZq4s") == tmp_path / ".llmkb" / "state" / "sources" / "youtube__TIYnaNaZq4s.yaml"

    def test_report_file(self, tmp_path: Path) -> None:
        p = Paths(tmp_path)
        assert p.report_file("20260514T000000Z-sync-youtube-abc") == tmp_path / ".llmkb" / "reports" / "20260514T000000Z-sync-youtube-abc.yaml"

    def test_ensure_creates_dirs(self, tmp_path: Path) -> None:
        p = Paths(tmp_path / "new_wiki")
        p.ensure()
        for d in ["inbox", "raw", "pageindex", "wiki", "history", ".llmkb/state/sources", ".llmkb/reports", "history/sessions"]:
            assert (tmp_path / "new_wiki" / d).is_dir()


class TestSourceIdEncoding:
    def test_encode_youtube(self) -> None:
        assert _encode_source_id("youtube:TIYnaNaZq4s") == "youtube__TIYnaNaZq4s"

    def test_encode_substack(self) -> None:
        assert _encode_source_id("substack:paperswithbacktest/2026-05-10-title") == "substack__paperswithbacktest__2026-05-10-title"

    def test_encode_manual(self) -> None:
        assert _encode_source_id("manual:abc123") == "manual__abc123"

    def test_roundtrip_youtube(self) -> None:
        original = "youtube:TIYnaNaZq4s"
        encoded = _encode_source_id(original)
        decoded = _decode_source_id(encoded)
        assert decoded == original
        assert encoded == "youtube__TIYnaNaZq4s"

    def test_roundtrip_substack(self) -> None:
        original = "substack:paperswithbacktest/2026-05-10-title"
        encoded = _encode_source_id(original)
        decoded = _decode_source_id(encoded)
        assert decoded == original
        assert encoded == "substack__paperswithbacktest__2026-05-10-title"