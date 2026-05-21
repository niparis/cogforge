"""Configuration loading and validation for cogforge."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from cogforge.paths import Paths, resolve_wiki_root


@dataclass
class LongDocumentConfig:
    page_threshold: int = 10
    char_threshold: int = 20_000


@dataclass
class PdfPreprocessConfig:
    vlm_model: str = "qwen/qwen2.5-vl-72b-instruct"
    vlm_base_url: str = "https://openrouter.ai/api/v1"
    vlm_api_key_env: str = "OPENROUTER_API_KEY"


@dataclass
class SourceConfig:
    id: str
    connector: str
    enabled: bool = True
    cookies_txt: str | None = None
    language_preferences: list[str] = field(default_factory=list)
    root_title: str | None = None
    max_depth: int | None = None
    newsletter: str | None = None
    publication: str | None = None
    playlist_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], connector_name: str) -> "SourceConfig":
        return cls(
            id=data.get("id", ""),
            connector=connector_name,
            enabled=data.get("enabled", True),
            cookies_txt=data.get("cookies_txt"),
            language_preferences=data.get("language_preferences", []),
            root_title=data.get("root_title"),
            max_depth=data.get("max_depth"),
            newsletter=data.get("newsletter"),
            publication=data.get("publication"),
            playlist_id=data.get("playlist_id"),
        )


@dataclass
class AgentConfig:
    """A single agent entry in the `agents:` fallback list.

    The runner walks this list in order. When the active agent hits a rate
    limit, the runner advances to the next entry and retries the same item.
    """
    cli: str                                                # "claude" or "opencode"
    model: str | None = None                                # CLI's default if None
    extra_args: list[str] = field(default_factory=list)
    timeout_seconds: int = 1800                             # 30 min per item
    rate_limit_patterns: list[str] | None = None            # falls back to defaults per cli

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentConfig":
        if not isinstance(data, dict):
            raise ValueError(f"agent entry must be a mapping, got {type(data).__name__}")
        cli = data.get("cli")
        if not cli:
            raise ValueError("agent entry missing required 'cli' field")
        if cli not in ("claude", "opencode"):
            raise ValueError(f"agent.cli must be 'claude' or 'opencode', got {cli!r}")
        extra_args = data.get("extra_args", []) or []
        if not isinstance(extra_args, list):
            raise ValueError(f"agent.extra_args must be a list, got {type(extra_args).__name__}")
        rl_patterns = data.get("rate_limit_patterns")
        if rl_patterns is not None and not isinstance(rl_patterns, list):
            raise ValueError(
                f"agent.rate_limit_patterns must be a list, got {type(rl_patterns).__name__}"
            )
        return cls(
            cli=cli,
            model=data.get("model"),
            extra_args=[str(a) for a in extra_args],
            timeout_seconds=int(data.get("timeout_seconds", 1800)),
            rate_limit_patterns=[str(p) for p in rl_patterns] if rl_patterns else None,
        )


@dataclass
class Config:
    version: int = 1
    defaults: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, list[SourceConfig]] = field(default_factory=dict)
    agents: list[AgentConfig] = field(default_factory=list)

    @property
    def long_document(self) -> LongDocumentConfig:
        raw = self.defaults.get("long_document", {})
        return LongDocumentConfig(
            page_threshold=raw.get("page_threshold", 10),
            char_threshold=raw.get("char_threshold", 20_000),
        )

    @property
    def pdf_preprocess(self) -> PdfPreprocessConfig:
        raw = self.defaults.get("pdf_preprocess", {})
        vlm = raw.get("vlm", {}) if isinstance(raw, dict) else {}
        return PdfPreprocessConfig(
            vlm_model=vlm.get("model", "qwen/qwen2.5-vl-72b-instruct"),
            vlm_base_url=vlm.get("base_url", "https://openrouter.ai/api/v1"),
            vlm_api_key_env=vlm.get("api_key_env", "OPENROUTER_API_KEY"),
        )

    @property
    def output_format(self) -> str:
        return self.defaults.get("output_format", "json")


def load_config(path: Path) -> Config:
    """Load and parse a sources.yaml config file."""
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raw = {}

    if not isinstance(raw, dict):
        raise ValueError("Config root must be a mapping")

    config = Config(version=raw.get("version", 1))

    # Defaults
    defaults = raw.get("defaults", {})
    if isinstance(defaults, dict):
        config.defaults = defaults

    # Sources
    sources = raw.get("sources", {})
    if isinstance(sources, dict):
        for conn_name, conn_sources in sources.items():
            if isinstance(conn_sources, list):
                config.sources[conn_name] = [
                    SourceConfig.from_dict(s, conn_name)
                    for s in conn_sources
                    if isinstance(s, dict)
                ]

    # Agents (fallback list used by `cogforge inbox run`)
    agents_raw = raw.get("agents", [])
    if isinstance(agents_raw, list):
        config.agents = [
            AgentConfig.from_dict(a) for a in agents_raw if isinstance(a, dict)
        ]

    return config


def validate_config(config: Config, config_path: Path) -> list[str]:
    """Validate a loaded config, return list of errors."""
    errors: list[str] = []

    if not config_path.is_file():
        errors.append(f"Config file not found: {config_path}")
        return errors

    sources = config.sources
    for conn_name, conn_sources in sources.items():
        for i, src in enumerate(conn_sources):
            if not src.id:
                errors.append(f"Source '{conn_name}[{i}]' missing required 'id'")

    return errors


def default_config() -> Config:
    """Return a Config with sensible defaults and no sources."""
    return Config(
        version=1,
        defaults={
            "output_format": "json",
            "long_document": {
                "page_threshold": 10,
                "char_threshold": 20_000,
            },
        },
    )
