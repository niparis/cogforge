"""cogforge - Agent-facing CLI for maintaining the LLM wiki."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cogforge")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
