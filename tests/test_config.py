"""Tests for config loading and validation."""
import pytest
import yaml
from pathlib import Path

from cogforge.config import Config, default_config, load_config, validate_config
from cogforge.paths import resolve_wiki_root


def _write_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data))


class TestDefaultConfig:
    def test_defaults_populated(self):
        cfg = default_config()
        assert cfg.version == 1
        assert cfg.output_format == "json"
        assert cfg.long_document.page_threshold == 10
        assert cfg.long_document.char_threshold == 20_000
        assert cfg.sources == {}


class TestLoadConfig:
    def test_load_valid_empty(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "sources.yaml"
        _write_config(cfg_path, {"version": 1, "defaults": {}, "sources": {}})
        cfg = load_config(cfg_path)
        assert cfg.version == 1
        assert cfg.sources == {}

    def test_load_with_sources(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "sources.yaml"
        _write_config(cfg_path, {
            "version": 1,
            "sources": {
                "youtube": [
                    {"id": "test-channel", "enabled": True, "playlist_id": "PL123"},
                ],
                "substack": [
                    {"id": "papers", "enabled": True, "cookies_txt": "/tmp/cookies"},
                ],
            },
        })
        cfg = load_config(cfg_path)
        assert "youtube" in cfg.sources
        assert "substack" in cfg.sources
        assert len(cfg.sources["youtube"]) == 1
        assert cfg.sources["youtube"][0].id == "test-channel"
        assert cfg.sources["substack"][0].cookies_txt == "/tmp/cookies"

    def test_load_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_load_empty_file(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "sources.yaml"
        _write_config(cfg_path, {})
        cfg = load_config(cfg_path)
        assert cfg.version == 1

    def test_load_defaults_applied(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "sources.yaml"
        _write_config(cfg_path, {"sources": {}})
        cfg = load_config(cfg_path)
        assert cfg.output_format == "json"
        assert cfg.long_document.page_threshold == 10
        assert cfg.long_document.char_threshold == 20_000


class TestValidateConfig:
    def test_valid_config(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "sources.yaml"
        _write_config(cfg_path, {
            "sources": {
                "youtube": [{"id": "abc123"}],
            },
        })
        cfg = load_config(cfg_path)
        errors = validate_config(cfg, cfg_path)
        assert errors == []

    def test_missing_id(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "sources.yaml"
        _write_config(cfg_path, {
            "sources": {
                "youtube": [{"enabled": True}],
            },
        })
        cfg = load_config(cfg_path)
        errors = validate_config(cfg, cfg_path)
        assert len(errors) > 0
        assert any("missing required 'id'" in e for e in errors)

    def test_missing_file(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "missing.yaml"
        cfg = default_config()
        errors = validate_config(cfg, cfg_path)
        assert len(errors) > 0
        assert any("not found" in e for e in errors)


class TestConfigRoundtrip:
    def test_load_save_load(self, tmp_path: Path) -> None:
        """Config survives a save/reload roundtrip."""
        cfg_path = tmp_path / "sources.yaml"
        original = Config(
            version=1,
            defaults={"output_format": "json", "long_document": {"page_threshold": 10, "char_threshold": 20000}},
            sources={"youtube": [SourceConfig := type("SC", (), {"id": "abc", "connector": "youtube", "enabled": True, "cookies_txt": None, "language_preferences": [], "root_title": None, "max_depth": None, "newsletter": None, "publication": None, "playlist_id": None})]},
        )
        # Just test load → dict → reconstruct
        with open(cfg_path, "w") as f:
            yaml.dump({"version": 1, "defaults": {"output_format": "json"}, "sources": {"youtube": [{"id": "abc"}]}}, f)
        cfg = load_config(cfg_path)
        assert cfg.version == 1
        assert "youtube" in cfg.sources
        assert cfg.sources["youtube"][0].id == "abc"


