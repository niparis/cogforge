"""Document metadata and output path helpers."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DocumentMeta:
    document_id: str
    source_path: Path
    source_sha256: str
    file_name: str
    out_dir: Path

    @property
    def pages_dir(self) -> Path:
        return self.out_dir / "pages"

    @property
    def tables_dir(self) -> Path:
        return self.out_dir / "tables"

    @property
    def visuals_dir(self) -> Path:
        return self.out_dir / "visuals"

    @property
    def enriched_dir(self) -> Path:
        return self.out_dir / "enriched"

    @property
    def enriched_path(self) -> Path:
        return self.enriched_dir / f"{self.document_id}.enriched.md"


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def register_document(pdf_path: Path, out_dir: Path) -> DocumentMeta:
    document_id = pdf_path.stem
    sha256 = compute_sha256(pdf_path)
    for sub in ("pages", "tables", "visuals", "enriched"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)
    return DocumentMeta(
        document_id=document_id,
        source_path=pdf_path,
        source_sha256=sha256,
        file_name=pdf_path.name,
        out_dir=out_dir,
    )
