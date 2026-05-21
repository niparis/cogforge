"""Tests for source state model, serialization, and validation."""
import pytest
import yaml
from pathlib import Path

from cogforge.state import (
    SourceState,
    SourceStatus,
    encode_source_id,
    decode_source_id,
    load_state,
    save_state,
    validate_state,
    Origin,
    ContentInfo,
    SourcePaths,
    PageIndexInfo,
    LastError,
    RunsInfo,
    ExcludedInfo,
)


class TestSourceStateDataclass:
    def test_create_minimal(self) -> None:
        s = SourceState(id="youtube:abc", connector="youtube", status="inbox")
        assert s.id == "youtube:abc"
        assert s.connector == "youtube"
        assert s.status == "inbox"

    def test_roundtrip_dict(self) -> None:
        original = SourceState(
            id="youtube:TIYnaNaZq4s",
            connector="youtube",
            document_type="transcript",
            status="inbox",
            origin=Origin(url="https://youtube.com/watch?v=TIYnaNaZq4s", title="Test", external_id="TIYnaNaZq4s"),
            content=ContentInfo(sha256="abcd1234", size_bytes=1000, estimated_chars=5000),
            paths=SourcePaths(inbox="llm_wiki/inbox/youtube/TIYnaNaZq4s.md"),
            pageindex=PageIndexInfo(required=True, status="pending"),
        )
        d = original.to_dict()
        restored = SourceState.from_dict(d)
        assert restored.id == original.id
        assert restored.status == original.status
        assert restored.origin.url == original.origin.url
        assert restored.content.sha256 == original.content.sha256
        assert restored.paths.inbox == original.paths.inbox
        assert restored.pageindex.required == original.pageindex.required


class TestSourceIdEncoding:
    def test_encode(self) -> None:
        assert encode_source_id("youtube:TIYnaNaZq4s") == "youtube__TIYnaNaZq4s"
        assert encode_source_id("substack:papers/test") == "substack__papers__test"

    def test_decode(self) -> None:
        assert decode_source_id("youtube__TIYnaNaZq4s") == "youtube:TIYnaNaZq4s"
        assert decode_source_id("substack__papers__test") == "substack:papers/test"


class TestSaveLoadState:
    def test_save_and_load(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state" / "sources"
        state_dir.mkdir(parents=True)

        state = SourceState(
            id="youtube:abc",
            connector="youtube",
            status="inbox",
            origin=Origin(url="https://youtube.com/watch?v=abc", title="Test"),
            content=ContentInfo(sha256="abcd1234", estimated_chars=5000),
            paths=SourcePaths(inbox="llm_wiki/inbox/youtube/abc.md"),
        )
        saved = save_state(state_dir, state)
        assert saved.is_file()
        assert "youtube__abc.yaml" in saved.name

        loaded = load_state(state_dir, "youtube:abc")
        assert loaded is not None
        assert loaded.id == "youtube:abc"
        assert loaded.status == "inbox"
        assert loaded.origin.url == "https://youtube.com/watch?v=abc"

    def test_load_missing_state(self, tmp_path: Path) -> None:
        result = load_state(tmp_path, "youtube:nope")
        assert result is None

    def test_load_from_empty_dir(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = load_state(empty_dir, "youtube:abc")
        assert result is None


class TestValidateState:
    def test_empty_dir(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        result = validate_state(empty)
        assert result["valid"] is True
        assert result["sources_checked"] == 0

    def test_valid_state(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        state = SourceState(id="youtube:abc", connector="youtube", status="inbox")
        save_state(state_dir, state)
        result = validate_state(state_dir)
        assert result["valid"] is True
        assert result["sources_checked"] == 1
        assert len(result["errors"]) == 0

    def test_invalid_status(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        state = SourceState(id="youtube:abc", connector="youtube", status="invalid_status")
        save_state(state_dir, state)
        result = validate_state(state_dir)
        assert result["valid"] is False
        assert any("invalid_status" in e for e in result["errors"])

    def test_duplicate_ids(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        state = SourceState(id="youtube:abc", connector="youtube", status="inbox")
        save_state(state_dir, state)
        # Save again with same ID - filename encodes to same file
        state2 = SourceState(id="youtube:abc", connector="youtube", status="processed")
        save_state(state_dir, state2)  # overwrites the same file
        # To test duplicate detection, manually create two differently-named files with same ID
        from cogforge.state import SourceState as SS, encode_source_id
        import yaml
        fname1 = encode_source_id("youtube:abc") + ".yaml"
        # Create a second file with the same ID but different filename
        data = state.to_dict()
        data["content"] = {"sha256": "other"}
        (state_dir / f"other__{fname1}").write_text(yaml.dump(data))
        result = validate_state(state_dir)
        assert result["valid"] is False
        assert any("Duplicate" in e for e in result["errors"])

    def test_missing_dir_returns_info(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent"
        result = validate_state(missing)
        assert result["valid"] is True
        assert len(result["warnings"]) == 1
        assert "No state directory found" in result["warnings"][0]


class TestDataclassDefaults:
    def test_origin_defaults(self) -> None:
        o = Origin()
        assert o.url is None
        assert o.title is None

    def test_content_defaults(self) -> None:
        c = ContentInfo()
        assert c.sha256 is None
        assert c.size_bytes is None

    def test_excluded_info(self) -> None:
        e = ExcludedInfo(reason="duplicate", note="test")
        assert e.reason == "duplicate"
        d = e.to_dict()
        assert d["reason"] == "duplicate"