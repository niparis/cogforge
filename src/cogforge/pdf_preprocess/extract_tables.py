"""Table extraction from PDF pages using PyMuPDF."""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd

from cogforge.pdf_preprocess.manifest import TableArtifact


def extract_tables(
    page: fitz.Page,
    page_number: int,
    document_id: str,
    tables_dir: Path,
) -> tuple[list[TableArtifact], list[str]]:
    """Extract tables from a page. Returns (artifacts, errors)."""
    artifacts: list[TableArtifact] = []
    errors: list[str] = []

    try:
        found = page.find_tables()
        tables = found.tables if hasattr(found, "tables") else list(found)
    except Exception as e:
        errors.append(f"Table detection failed: {e}")
        return artifacts, errors

    for idx, table in enumerate(tables, start=1):
        table_id = f"page-{page_number:03d}-table-{idx:03d}"
        csv_path = tables_dir / f"{table_id}.csv"
        md_path = tables_dir / f"{table_id}.md"

        try:
            data = table.extract()
            if not data or not any(any(cell for cell in row) for row in data):
                artifacts.append(TableArtifact(
                    table_id=table_id,
                    page_number=page_number,
                    csv_path=str(csv_path),
                    markdown_path=str(md_path),
                    rows=0,
                    columns=0,
                    extraction_status="EMPTY",
                ))
                continue

            header = data[0] if data[0] else [f"col{i}" for i in range(len(data[0]))]
            df = pd.DataFrame(data[1:], columns=header)
            df.to_csv(csv_path, index=False)

            md_table = df.to_markdown(index=False)
            frontmatter = (
                f"---\n"
                f"document_id: {document_id}\n"
                f"page: {page_number}\n"
                f"artifact_type: table\n"
                f"table_id: {table_id}\n"
                f"---\n"
            )
            md_path.write_text(
                frontmatter + f"# Table {table_id}\n\n{md_table}\n",
                encoding="utf-8",
            )

            artifacts.append(TableArtifact(
                table_id=table_id,
                page_number=page_number,
                csv_path=str(csv_path),
                markdown_path=str(md_path),
                rows=len(df),
                columns=len(df.columns),
                extraction_status="SUCCESS",
            ))
        except Exception as e:
            errors.append(f"Table {table_id} extraction failed: {e}")
            artifacts.append(TableArtifact(
                table_id=table_id,
                page_number=page_number,
                csv_path=str(csv_path),
                markdown_path=str(md_path),
                rows=0,
                columns=0,
                extraction_status="FAILED",
            ))

    return artifacts, errors
