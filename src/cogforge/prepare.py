"""Inbox source preparation: validate package, enrich PDFs, detect long documents, run PageIndex."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from cogforge.config import Config
from cogforge.pageindexing import detect_long_document, run_pageindex
from cogforge.paths import Paths
from cogforge.state import load_state, save_state


@dataclass
class PrepareResult:
    """Result of preparing an inbox source for LLM compilation."""
    source_id: str
    package_valid: bool = True
    package_issues: list[str] = field(default_factory=list)
    pdf_enrich_status: str | None = None  # skipped | success | failed
    pdf_enrich_details: dict[str, Any] = field(default_factory=dict)
    long_document_detected: bool = False
    pageindex_status: str | None = None  # skipped | complete | failed
    pageindex_artifact_path: str | None = None
    pageindex_error: str | None = None
    pageindex_page_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "source_id": self.source_id,
            "package_valid": self.package_valid,
            "long_document_detected": self.long_document_detected,
            "pageindex_required": self.long_document_detected,
        }
        if self.package_issues:
            data["package_issues"] = self.package_issues
        if self.pdf_enrich_status:
            data["pdf_enrich"] = {"status": self.pdf_enrich_status, **self.pdf_enrich_details}
        if self.pageindex_status:
            data["pageindex"] = {
                "status": self.pageindex_status,
                "artifact_path": self.pageindex_artifact_path,
                "error": self.pageindex_error,
                "page_count": self.pageindex_page_count,
            }
        return data


def _check_required_env(config: Config) -> list[dict[str, str]]:
    """Return a list of missing-env-var problems, keyed by the config field that references them.

    Currently checks: pdf_preprocess.vlm.api_key_env.
    Each entry: {"field": "...", "env_var": "...", "hint": "..."}
    """
    problems: list[dict[str, str]] = []
    pdf_cfg = config.pdf_preprocess
    key_name = pdf_cfg.vlm_api_key_env
    if key_name and not os.environ.get(key_name):
        problems.append({
            "field": "defaults.pdf_preprocess.vlm.api_key_env",
            "env_var": key_name,
            "hint": (
                f"{key_name} is not set in the environment. "
                f"Add it to <wiki_root>/.env or the parent project's .env, "
                f"or export it before running cogforge. "
                f"Without it, PDF visual summaries will silently fail. "
                f"Use --allow-missing-vlm-key to skip this check."
            ),
        })
    return problems


def _read_frontmatter(path: Path) -> dict[str, Any]:
    """Return the YAML frontmatter dict from a Markdown file, or {} if absent."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            return yaml.safe_load(text[4:end]) or {}
    return {}


def prepare_inbox_source(
    source_id: str,
    paths: Paths,
    config: Config,
    *,
    no_pageindex: bool = False,
    force_pageindex: bool = False,
    char_threshold: int | None = None,
    page_threshold: int | None = None,
    no_pdf_enrich: bool = False,
    force_pdf_enrich: bool = False,
    allow_missing_vlm_key: bool = False,
) -> PrepareResult:
    """Prepare one inbox source for LLM compilation.

    Steps:
      1. Validate source package (folder + index.md exist).
      2. If PDF connector: run PDF enrichment (VLM visual summaries, table extraction).
      3. Detect long documents based on config thresholds.
      4. If long document: run PageIndex.
      5. Return structured PrepareResult.
    """
    state_dir = paths.state_sources
    state = load_state(state_dir, source_id)
    if state is None:
        return PrepareResult(
            source_id=source_id,
            package_valid=False,
            package_issues=[f"State file not found for source: {source_id}"],
        )

    source_folder_name = None
    if state.paths.inbox:
        source_folder_name = Path(state.paths.inbox).name

    inbox_folder = paths.inbox / state.connector / source_folder_name if source_folder_name else None

    package_valid = True
    package_issues: list[str] = []
    if inbox_folder and not inbox_folder.is_dir():
        package_valid = False
        package_issues.append(f"inbox folder not found: {state.paths.inbox}")
    elif inbox_folder:
        index_md = inbox_folder / "index.md"
        if not index_md.is_file():
            package_valid = False
            package_issues.append("index.md not found in inbox folder")

    # PDF enrichment (pdf connector only, before PageIndex)
    pdf_enrich_status: str | None = None
    pdf_enrich_details: dict[str, Any] = {}
    if state.connector == "pdf" and not no_pdf_enrich and inbox_folder and inbox_folder.is_dir():
        env_problems = _check_required_env(config)
        if env_problems and not allow_missing_vlm_key:
            # Return failure so caller can decide what to do
            return PrepareResult(
                source_id=source_id,
                package_valid=package_valid,
                package_issues=package_issues + [p["hint"] for p in env_problems],
                pdf_enrich_status="failed",
                pdf_enrich_details={"error": "missing_env", "hints": [p["hint"] for p in env_problems]},
            )

        from cogforge.pdf_preprocess import ingest_pdf, PDFPreprocessConfig
        from cogforge.pdf_preprocess.config import VLMConfig

        source_file = _read_frontmatter(inbox_folder / "index.md").get("source_file")
        pdf_path = paths.papers / source_file if source_file else None
        enriched_dir = inbox_folder / "enriched"
        already_done = enriched_dir.is_dir() and not force_pdf_enrich

        if already_done:
            pdf_enrich_status = "skipped"
            pdf_enrich_details = {"reason": "already enriched"}
        elif not pdf_path or not pdf_path.exists():
            logger.warning(f"PDF file not found for {source_id}: {source_file!r}")
            pdf_enrich_status = "skipped"
            pdf_enrich_details = {"reason": f"pdf not found: {source_file}"}
        else:
            try:
                pdf_cfg = config.pdf_preprocess
                vlm_enabled = not bool(env_problems and allow_missing_vlm_key)
                cfg = PDFPreprocessConfig(
                    vlm=VLMConfig(
                        enabled=vlm_enabled,
                        model=pdf_cfg.vlm_model,
                        base_url=pdf_cfg.vlm_base_url,
                        api_key_env=pdf_cfg.vlm_api_key_env,
                    ),
                    force=force_pdf_enrich,
                )
                manifest = ingest_pdf(pdf_path, inbox_folder, cfg)
                enriched_md = enriched_dir / f"{manifest.document_id}.enriched.md"
                shutil.copy(enriched_md, inbox_folder / "index.md")
                state.content.estimated_chars = sum(p.text_chars for p in manifest.pages)
                state.content.estimated_pages = manifest.page_count
                save_state(state_dir, state)
                pdf_enrich_status = "success"
                pdf_enrich_details = {"pages": manifest.page_count, "pdf_path": str(pdf_path)}
            except Exception as exc:
                logger.error(f"PDF enrichment failed for {source_id}: {exc}")
                pdf_enrich_status = "failed"
                pdf_enrich_details = {"error": str(exc)}

    # Long document detection and PageIndex
    is_long = False
    if not no_pageindex:
        is_long = detect_long_document(state, config, char_threshold, page_threshold)

    pageindex_status: str | None = None
    pageindex_artifact_path: str | None = None
    pageindex_error: str | None = None
    pageindex_page_count: int | None = None

    if is_long and not no_pageindex:
        pi_result = run_pageindex(
            state, paths, config,
            force=force_pageindex,
            char_override=char_threshold,
            page_override=page_threshold,
        )
        state.pageindex.required = is_long
        state.pageindex.status = pi_result.status
        state.pageindex.artifact_path = pi_result.artifact_path
        state.pageindex.error = pi_result.error
        save_state(state_dir, state)
        pageindex_status = pi_result.status
        pageindex_artifact_path = pi_result.artifact_path
        pageindex_error = pi_result.error
        pageindex_page_count = pi_result.page_count
    elif not is_long:
        pageindex_status = "skipped"

    return PrepareResult(
        source_id=source_id,
        package_valid=package_valid,
        package_issues=package_issues,
        pdf_enrich_status=pdf_enrich_status,
        pdf_enrich_details=pdf_enrich_details,
        long_document_detected=is_long,
        pageindex_status=pageindex_status,
        pageindex_artifact_path=pageindex_artifact_path,
        pageindex_error=pageindex_error,
        pageindex_page_count=pageindex_page_count,
    )
