"""Tests for PDF enrichment wired into inbox prepare."""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import fitz  # PyMuPDF
import pytest
import yaml

from cogforge.cli import _read_frontmatter


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Sample PDF content. " * 60, fontsize=11)
    doc.save(str(path))
    doc.close()


def _make_wiki(tmp_path: Path, source_name: str = "Test Papers — sample") -> tuple[Path, Path, Path]:
    """Set up a minimal wiki with one pdf inbox source. Returns (wiki_root, inbox_folder, pdf_path)."""
    wiki_root = tmp_path / "llm_wiki"
    papers_dir = wiki_root / "raw" / "papers"
    papers_dir.mkdir(parents=True)
    inbox_folder = wiki_root / "inbox" / "pdf" / source_name
    inbox_folder.mkdir(parents=True)
    state_dir = wiki_root / ".llmkb" / "state" / "sources"
    state_dir.mkdir(parents=True)

    # sources.yaml with mock VLM so tests need no API key
    (wiki_root / "sources.yaml").write_text(
        "version: 1\ndefaults:\n  pdf_preprocess:\n    vlm:\n      model: mock\n",
        encoding="utf-8",
    )

    pdf_filename = f"{source_name}.pdf"
    pdf_path = papers_dir / pdf_filename
    _make_pdf(pdf_path)

    # Write index.md with source_file frontmatter
    (inbox_folder / "index.md").write_text(
        f"---\nconnector: pdf\ntitle: sample\nsource_file: {pdf_filename}\npage_count: 1\n---\n\nSample text.",
        encoding="utf-8",
    )

    # Write state file
    source_id = f"pdf:{source_name}"
    encoded = source_id.replace(":", "__").replace("/", "__")
    state = {
        "version": 1,
        "id": source_id,
        "connector": "pdf",
        "document_type": "pdf",
        "status": "inbox",
        "origin": {"title": "sample", "fetched_at": "2026-05-16T00:00:00+00:00"},
        "content": {"estimated_chars": 1000, "estimated_pages": 1},
        "paths": {"inbox": f"inbox/pdf/{source_name}"},
        "pageindex": {},
        "last_error": {},
        "excluded": {},
        "runs": {"last_sync": "2026-05-16T00:00:00+00:00"},
    }
    (state_dir / f"{encoded}.yaml").write_text(yaml.dump(state), encoding="utf-8")

    return wiki_root, inbox_folder, pdf_path


def _run_prepare(wiki_root: Path, source_id: str, extra_args: list[str] | None = None) -> dict:
    cmd = [
        sys.executable, "-m", "cogforge",
        "--wiki-root", str(wiki_root),
        "--config", str(wiki_root / "sources.yaml"),
        "--format", "json",
        "inbox", "prepare", source_id,
        "--no-pageindex",
        "--allow-missing-vlm-key",
    ] + (extra_args or [])
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"CLI failed:\n{result.stderr}\n{result.stdout}"
    # PyMuPDF may print informational messages to stdout before the JSON object.
    # Find the first { to locate the start of the JSON payload.
    stdout = result.stdout
    json_start = stdout.find("{")
    assert json_start >= 0, f"No JSON found in output:\n{stdout}"
    return json.loads(stdout[json_start:])


# ── unit tests for helpers ────────────────────────────────────────────────────

def test_read_frontmatter_basic(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("---\ntitle: Hello\npage_count: 5\n---\n\nBody.", encoding="utf-8")
    fm = _read_frontmatter(f)
    assert fm["title"] == "Hello"
    assert fm["page_count"] == 5


def test_read_frontmatter_missing_file(tmp_path):
    assert _read_frontmatter(tmp_path / "nope.md") == {}


def test_read_frontmatter_no_frontmatter(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("Just plain text.", encoding="utf-8")
    assert _read_frontmatter(f) == {}


# ── integration tests via CLI ─────────────────────────────────────────────────

def test_pdf_enrich_success(tmp_path):
    wiki_root, inbox_folder, _ = _make_wiki(tmp_path)
    result = _run_prepare(wiki_root, "pdf:Test Papers — sample")
    assert result["pdf_enrich"]["status"] == "success"
    assert result["pdf_enrich"]["pages"] >= 1


def test_pdf_enrich_replaces_index_md(tmp_path):
    wiki_root, inbox_folder, _ = _make_wiki(tmp_path)
    original = (inbox_folder / "index.md").read_text()
    _run_prepare(wiki_root, "pdf:Test Papers — sample")
    new_content = (inbox_folder / "index.md").read_text()
    assert new_content != original
    assert "pipeline_version" in new_content


def test_pdf_enrich_creates_artifacts(tmp_path):
    wiki_root, inbox_folder, _ = _make_wiki(tmp_path)
    _run_prepare(wiki_root, "pdf:Test Papers — sample")
    assert (inbox_folder / "manifest.json").exists()
    assert (inbox_folder / "summary.md").exists()
    assert (inbox_folder / "enriched").is_dir()
    assert list((inbox_folder / "pages").glob("*.text.md"))


def test_pdf_enrich_skips_when_already_done(tmp_path):
    wiki_root, inbox_folder, _ = _make_wiki(tmp_path)
    # First run
    _run_prepare(wiki_root, "pdf:Test Papers — sample")
    mtime = (inbox_folder / "index.md").stat().st_mtime
    # Second run — should be skipped (cached)
    result = _run_prepare(wiki_root, "pdf:Test Papers — sample")
    assert result["pdf_enrich"]["status"] == "skipped"
    assert (inbox_folder / "index.md").stat().st_mtime == mtime


def test_pdf_enrich_force_reruns(tmp_path):
    import time
    wiki_root, inbox_folder, _ = _make_wiki(tmp_path)
    _run_prepare(wiki_root, "pdf:Test Papers — sample")
    mtime1 = (inbox_folder / "index.md").stat().st_mtime
    time.sleep(0.05)
    result = _run_prepare(wiki_root, "pdf:Test Papers — sample", ["--force-pdf-enrich"])
    assert result["pdf_enrich"]["status"] == "success"
    assert (inbox_folder / "index.md").stat().st_mtime >= mtime1


def test_no_pdf_enrich_flag_skips(tmp_path):
    wiki_root, inbox_folder, _ = _make_wiki(tmp_path)
    original = (inbox_folder / "index.md").read_text()
    result = _run_prepare(wiki_root, "pdf:Test Papers — sample", ["--no-pdf-enrich"])
    assert "pdf_enrich" not in result
    assert (inbox_folder / "index.md").read_text() == original


def test_pdf_not_found_returns_skipped(tmp_path):
    wiki_root, inbox_folder, pdf_path = _make_wiki(tmp_path)
    pdf_path.unlink()  # remove the PDF
    result = _run_prepare(wiki_root, "pdf:Test Papers — sample")
    assert result["pdf_enrich"]["status"] == "skipped"
    assert "pdf not found" in result["pdf_enrich"]["reason"]


def test_non_pdf_connector_not_enriched(tmp_path):
    """A substack or youtube source should not trigger PDF enrichment."""
    wiki_root = tmp_path / "llm_wiki"
    inbox_folder = wiki_root / "inbox" / "substack" / "my-newsletter"
    inbox_folder.mkdir(parents=True)
    (inbox_folder / "index.md").write_text("---\ntitle: post\n---\n\nBody.", encoding="utf-8")
    state_dir = wiki_root / ".llmkb" / "state" / "sources"
    state_dir.mkdir(parents=True)
    (wiki_root / "sources.yaml").write_text(
        "version: 1\ndefaults:\n  pdf_preprocess:\n    vlm:\n      model: mock\n",
        encoding="utf-8",
    )
    source_id = "substack:my-newsletter"
    encoded = source_id.replace(":", "__")
    state = {
        "version": 1, "id": source_id, "connector": "substack",
        "document_type": None, "status": "inbox",
        "origin": {"title": "post", "fetched_at": "2026-05-16T00:00:00+00:00"},
        "content": {"estimated_chars": 500, "estimated_pages": 1},
        "paths": {"inbox": "inbox/substack/my-newsletter"},
        "pageindex": {}, "last_error": {}, "excluded": {},
        "runs": {"last_sync": "2026-05-16T00:00:00+00:00"},
    }
    (state_dir / f"{encoded}.yaml").write_text(yaml.dump(state), encoding="utf-8")

    result = _run_prepare(wiki_root, source_id)
    assert "pdf_enrich" not in result
