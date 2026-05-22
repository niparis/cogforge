# Cogforge Agent Instructions

You are working on Cogforge, the CLI/tooling repository.

Cogforge is code, not a knowledge base. 

## Boundaries

- Product, architecture, packaging, and migration decisions belong in this repository, not in a user's `llm_wiki/wiki/decisions`.
- Do not run `cogforge wiki session-new` or `cogforge wiki log` merely because you changed Cogforge code.

## Project Shape

- Python package: `src/cogforge`
- CLI command: `cogforge`
- Tests: `tests`
- Documentation: `docs`


## Common Commands

```bash
uv run pytest
uv run cogforge --help
uv run cogforge status --wiki-root /path/to/llm_wiki
```

## Release Workflow

- **Version source of truth**: `pyproject.toml` (`version = "x.y.z"`).
- **Tag convention**: `v` prefix, e.g. `v0.1.0`.
- **Auto-draft on tag push**: Pushing any `v*` tag triggers `.github/workflows/auto-draft-release.yaml`, which creates a draft release with auto-generated notes.
- **Trigger**: Publishing the draft release (not a bare git tag push) fires `.github/workflows/publish.yaml`.
- **What it does**: Checks out the release tag, runs `uv build`, then `uv publish` to PyPI via OIDC trusted publishing.
- **To release**:
  1. Ensure `pyproject.toml` version is bumped.
  2. Commit the version bump.
  3. Create and push an annotated tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`
  4. The draft release appears automatically on GitHub.
  5. Go to GitHub → Releases, open the draft, review the notes, and click **Publish release**.


