"""Apple Notes connector: export, parse, write."""
from __future__ import annotations

from loguru import logger as log
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cogforge.paths import Paths
from cogforge.state import (
    ContentInfo,
    LastError,
    Origin,
    RunsInfo,
    SourcePaths,
    SourceState,
    SourceStatus,
    load_state,
    save_state,
)



NOTES_HOME = Path.home() / "Library/Group Containers/group.com.apple.notes"
NOTESTORE = NOTES_HOME / "NoteStore.sqlite"
ACCOUNTS_DIR = NOTES_HOME / "Accounts"

TOKEN_LINK_RE = re.compile(
    r"applenotes:note/([0-9A-Fa-f-]+)", re.IGNORECASE
)
INLINE_LINK_UTI = "com.apple.notes.inlinetextattachment.link"
PDF_UTIS = {"com.adobe.pdf", "public.pdf", "com.apple.paper.doc.pdf"}


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class NoteRow:
    pk: int
    identifier: str
    title: str


@dataclass
class AppleNotesSyncResult:
    connector: str = "apple-notes"
    new_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    total_discovered: int = 0
    source_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    pdfs: dict[str, list[str]] = field(default_factory=dict)  # source_id → [pdf_filenames]


# ── Database access ────────────────────────────────────────────────────────────

def _open_db() -> sqlite3.Connection:
    if not NOTESTORE.exists():
        raise FileNotFoundError(f"NoteStore.sqlite not found at {NOTESTORE}")

    conn = sqlite3.connect(f"file:{NOTESTORE}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.DatabaseError as e:
        raise PermissionError(
            "Cannot read Apple Notes database — Full Disk Access required.\n"
            "Grant it to your terminal:\n"
            "  System Settings → Privacy & Security → Full Disk Access → "
            "enable for your terminal app, then restart the terminal."
        ) from e
    return conn


def _entity_ids(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT Z_NAME, Z_ENT FROM Z_PRIMARYKEY").fetchall()
    return {r["Z_NAME"]: r["Z_ENT"] for r in rows}


def _detect_columns(conn: sqlite3.Connection, ents: dict[str, int]) -> dict[str, str]:
    header_cols = [
        r["name"] for r in conn.execute("PRAGMA table_info(ZICCLOUDSYNCINGOBJECT)")
    ]
    candidates = [c for c in header_cols if c == "ZACCOUNT" or c.startswith("ZACCOUNT")]

    def _fk_for_entity(ent_id: int) -> str | None:
        select = ", ".join(candidates)
        r = conn.execute(
            f"SELECT {select} FROM ZICCLOUDSYNCINGOBJECT "
            f"WHERE Z_ENT = ? AND ({' OR '.join(f'{c} IS NOT NULL' for c in candidates)}) "
            f"LIMIT 1",
            (ent_id,),
        ).fetchone()
        if not r:
            return None
        for c in candidates:
            if r[c] is not None:
                return c
        return None

    note_fk = _fk_for_entity(ents["ICNote"])
    if not note_fk:
        raise RuntimeError("Could not locate ICNote account FK column")
    return {"note_account_fk": note_fk}


def _find_starting_note(
    conn: sqlite3.Connection, ents: dict[str, int], title: str
) -> NoteRow:
    rows = conn.execute(
        """
        SELECT Z_PK, ZIDENTIFIER, ZTITLE1
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE Z_ENT = ?
          AND ZTITLE1 = ?
          AND COALESCE(ZMARKEDFORDELETION, 0) = 0
        """,
        (ents["ICNote"], title),
    ).fetchall()
    if not rows:
        raise ValueError(f'No note found with title "{title}".')
    if len(rows) > 1:
        log.warning('{} notes match "{}", using first.', len(rows), title)
    r = rows[0]
    return NoteRow(pk=r["Z_PK"], identifier=r["ZIDENTIFIER"], title=r["ZTITLE1"])


def _find_note_by_uuid(
    conn: sqlite3.Connection, ents: dict[str, int], uuid: str
) -> NoteRow | None:
    r = conn.execute(
        """
        SELECT Z_PK, ZIDENTIFIER, ZTITLE1
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE Z_ENT = ?
          AND ZIDENTIFIER = ? COLLATE NOCASE
          AND COALESCE(ZMARKEDFORDELETION, 0) = 0
        """,
        (ents["ICNote"], uuid),
    ).fetchone()
    if not r:
        return None
    return NoteRow(pk=r["Z_PK"], identifier=r["ZIDENTIFIER"], title=r["ZTITLE1"])


def _outbound_link_uuids(
    conn: sqlite3.Connection, ents: dict[str, int], note_pk: int
) -> list[str]:
    rows = conn.execute(
        """
        SELECT ZTOKENCONTENTIDENTIFIER AS tok
        FROM ZICCLOUDSYNCINGOBJECT
        WHERE Z_ENT = ?
          AND ZTYPEUTI1 = ?
          AND (ZNOTE = ? OR ZNOTE1 = ?)
          AND COALESCE(ZMARKEDFORDELETION, 0) = 0
        """,
        (ents["ICInlineAttachment"], INLINE_LINK_UTI, note_pk, note_pk),
    ).fetchall()
    seen: dict[str, None] = {}
    for r in rows:
        tok = r["tok"] or ""
        m = TOKEN_LINK_RE.search(tok)
        if m:
            seen.setdefault(m.group(1), None)
    return list(seen)


# ── AppleScript helpers ────────────────────────────────────────────────────────

_BODY_SCRIPT = """\
on run argv
    tell application "Notes"
        return body of note id (item 1 of argv)
    end tell
end run
"""


def _osascript(script: str, timeout: int = 30) -> str:
    r = subprocess.run(
        ["osascript", "-"],
        input=script,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"osascript failed: {r.stderr.strip()}")
    return r.stdout


def _discover_store_uuid() -> str:
    out = _osascript(
        'tell application "Notes" to return id of note 1'
    ).strip()
    m = re.match(r"x-coredata://([^/]+)/", out)
    if not m:
        raise RuntimeError(f"Unexpected AppleScript note id: {out!r}")
    return m.group(1)


def _coredata_id(store_uuid: str, note_pk: int) -> str:
    return f"x-coredata://{store_uuid}/ICNote/p{note_pk}"


def _get_body_html(cdid: str) -> str:
    r = subprocess.run(
        ["osascript", "-", cdid],
        input=_BODY_SCRIPT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Could not fetch body for {cdid}: {r.stderr.strip()}")
    return r.stdout


# ── PDF attachments ────────────────────────────────────────────────────────────

def _pdf_attachments_for_note(
    conn: sqlite3.Connection,
    ents: dict[str, int],
    cols: dict[str, str],
    note_pk: int,
) -> list[tuple[str, Path]]:
    acct_col = cols["note_account_fk"]
    sql = f"""
    SELECT
        a.ZTYPEUTI          AS uti_a,
        a.ZFILENAME         AS att_filename,
        a.ZTITLE            AS att_title,
        m.ZIDENTIFIER       AS media_id,
        m.ZFILENAME         AS media_filename,
        m.ZTYPEUTI          AS uti_m,
        acc.ZIDENTIFIER     AS account_id
    FROM ZICCLOUDSYNCINGOBJECT a
    LEFT JOIN ZICCLOUDSYNCINGOBJECT m  ON m.Z_PK = a.ZMEDIA
    LEFT JOIN ZICCLOUDSYNCINGOBJECT n  ON n.Z_PK = a.ZNOTE
    LEFT JOIN ZICCLOUDSYNCINGOBJECT acc ON acc.Z_PK = n.{acct_col}
    WHERE a.ZNOTE = ?
      AND COALESCE(a.ZMARKEDFORDELETION, 0) = 0
    """
    rows = conn.execute(sql, (note_pk,)).fetchall()
    out: list[tuple[str, Path]] = []
    for r in rows:
        uti = (r["uti_a"] or r["uti_m"] or "").lower()
        if uti not in PDF_UTIS:
            continue
        media_id = r["media_id"]
        if not media_id:
            continue
        account_id = r["account_id"]
        if not account_id:
            continue
        filename = (
            r["media_filename"] or r["att_filename"] or r["att_title"] or f"{media_id}.pdf"
        )
        media_dir = ACCOUNTS_DIR / account_id / "Media" / media_id
        if not media_dir.is_dir():
            continue
        match = next(
            (p for p in media_dir.rglob(filename) if p.is_file()),
            None,
        ) or next(
            (p for p in media_dir.rglob("*.pdf") if p.is_file()),
            None,
        )
        if match is None:
            continue
        out.append((filename, match))
    return out


# ── Text utilities ─────────────────────────────────────────────────────────────

def _sanitize_filename(name: str) -> str:
    name = name.strip()
    if not name:
        return "untitled"
    name = re.sub(r"[/\\:\x00]", "-", name)
    name = re.sub(r"\s+", " ", name)
    return name[:200]


def _html_to_markdown(html: str, title: str) -> str:
    from markdownify import markdownify as md

    # Strip inline base64 image blobs before conversion — they produce
    # multi-hundred-KB single-line strings that are useless as text content.
    html = re.sub(r'src="data:image/[^"]*"', 'src=""', html)
    body_md = md(html, heading_style="ATX").strip()
    lines = body_md.splitlines()
    if lines and lines[0].strip().lstrip("#").strip() == title.strip():
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return f"# {title}\n\n" + "\n".join(lines).rstrip() + "\n"


# ── Issue writing ─────────────────────────────────────────────────────────────

def _write_note_issue(
    out_dir: Path,
    note: NoteRow,
    body_md: str,
) -> Path:
    """Write a single Apple Note as an issue package (index.md)."""
    from datetime import date

    import yaml

    folder_name = _sanitize_filename(note.title)
    folder = out_dir / folder_name
    folder.mkdir(parents=True, exist_ok=True)

    frontmatter = {
        "source": f"applenotes:note/{note.identifier}",
        "connector": "apple-notes",
        "title": note.title,
        "date_fetched": date.today().isoformat(),
        "note_identifier": note.identifier,
        "note_pk": note.pk,
    }

    fm = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    full_md = f"---\n{fm}\n---\n\n{body_md}"

    (folder / "index.md").write_text(full_md, encoding="utf-8")
    return folder


# ── Source state writing ──────────────────────────────────────────────────────

def _write_source_state(
    paths: Paths,
    source_id: str,
    note: NoteRow,
    status: str,
    *,
    error: str | None = None,
    estimated_chars: int | None = None,
) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    state = SourceState(
        version=1,
        id=source_id,
        connector="apple-notes",
        status=status,
        origin=Origin(
            url=f"applenotes:note/{note.identifier}",
            title=note.title,
            external_id=note.identifier,
            fetched_at=now,
        ),
        content=ContentInfo(estimated_chars=estimated_chars),
        paths=SourcePaths(
            inbox=f"inbox/apple-notes/{_sanitize_filename(note.title)}"
        ),
        runs=RunsInfo(last_sync=now),
        last_error=LastError(
            phase="sync",
            message=error,
            retryable=True,
            occurred_at=now,
        )
        if error
        else LastError(),
    )
    save_state(paths.state_sources, state)


# ── Sync Orchestration ────────────────────────────────────────────────────────


def sync_apple_notes(
    paths: Paths,
    config: Any,
    *,
    source_id: str | None = None,
    all_sources: bool = False,
    root_title: str | None = None,
    max_depth: int | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> AppleNotesSyncResult:
    """Export Apple Notes from configured root notes into the wiki inbox.

    Args:
        paths: Resolved wiki paths.
        config: Loaded config object.
        source_id: Export one configured Apple Notes root.
        all_sources: Export all enabled Apple Notes sources.
        root_title: Override root note title.
        max_depth: Limit graph traversal depth.
        dry_run: Report what would be done without writing files.
        verbose: Include debug output.

    Returns:
        AppleNotesSyncResult with counts and any errors.
    """
    from cogforge.config import Config

    if not isinstance(config, Config):
        config = Config()

    result = AppleNotesSyncResult()

    # Determine root titles to process
    root_titles: list[str] = []

    if all_sources:
        for src in config.sources.get("apple-notes", []):
            if src.enabled:
                title = root_title or src.root_title or src.id
                if title:
                    root_titles.append(title)
    elif source_id:
        for src in config.sources.get("apple-notes", []):
            if src.id == source_id and src.enabled:
                title = root_title or src.root_title or src.id
                if title:
                    root_titles.append(title)
                break
        else:
            # source_id might be the root title itself
            root_titles.append(root_title or source_id)
    elif root_title:
        root_titles.append(root_title)

    if not root_titles:
        result.errors.append("No Apple Notes root titles specified")
        return result

    conn = _open_db()
    try:
        ents = _entity_ids(conn)
        cols = _detect_columns(conn, ents)

        if "ICNote" not in ents:
            result.errors.append("Could not find ICNote entity")
            return result

        store_uuid = _discover_store_uuid()

        for title in root_titles:
            try:
                start = _find_starting_note(conn, ents, title)
            except ValueError as e:
                result.errors.append(str(e))
                continue

            if verbose:
                log.info("Root note: {} (pk={})", start.title, start.pk)

            if dry_run:
                result.total_discovered += 1
                result.source_ids.append(f"apple-notes:{start.identifier}")
                log.info("DRY RUN: would export note {}", start.title)
                continue

            _export_note_graph(
                conn, ents, cols, store_uuid, start, max_depth,
                paths, result, verbose,
            )

        return result
    finally:
        conn.close()


def _export_note_graph(
    conn: sqlite3.Connection,
    ents: dict[str, int],
    cols: dict[str, str],
    store_uuid: str,
    start: NoteRow,
    max_depth: int | None,
    paths: Paths,
    result: AppleNotesSyncResult,
    verbose: bool,
) -> None:
    """BFS export of a note graph from a starting root note."""
    out_dir = paths.connector_inbox("apple-notes")
    out_dir.mkdir(parents=True, exist_ok=True)
    attachments_dir = out_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    visited: set[int] = set()
    queue: deque[tuple[NoteRow, int]] = deque([(start, 0)])

    while queue:
        note, depth = queue.popleft()
        if note.pk in visited:
            continue
        visited.add(note.pk)
        result.total_discovered += 1

        # Always traverse links — even for already-processed notes,
        # so deeper notes can be discovered on re-runs
        if max_depth is None or depth < max_depth:
            for uuid in _outbound_link_uuids(conn, ents, note.pk):
                nxt = _find_note_by_uuid(conn, ents, uuid)
                if nxt is None or nxt.pk in visited:
                    continue
                queue.append((nxt, depth + 1))

        source_id = f"apple-notes:{note.identifier}"

        # Check if already processed
        existing_state = load_state(paths.state_sources, source_id)
        if existing_state and existing_state.status == SourceStatus.PROCESSED.value:
            result.skipped_count += 1
            log.info("Skipping already-processed: {}", note.title)
            continue

        log.info("[{}] depth={}  {}", result.total_discovered, depth, note.title)

        try:
            html = _get_body_html(_coredata_id(store_uuid, note.pk))
        except Exception as e:
            log.error("Body fetch failed for {}: {}", note.title, e)
            result.errors.append(f"{note.title}: body fetch failed - {e}")
            result.error_count += 1
            _write_source_state(
                paths, source_id, note, "failed", error=str(e)
            )
            continue

        body_md = _html_to_markdown(html, note.title)
        folder = _write_note_issue(out_dir, note, body_md)

        # Copy PDF attachments
        pdf_count = 0
        note_pdfs: list[str] = []
        for filename, src in _pdf_attachments_for_note(conn, ents, cols, note.pk):
            dest = attachments_dir / f"{_sanitize_filename(note.title)} — {_sanitize_filename(filename)}"
            note_pdfs.append(dest.name)
            if not dest.exists():
                try:
                    shutil.copy2(src, dest)
                    pdf_count += 1
                    log.info("  + PDF {}", dest.name)
                except OSError as e:
                    log.warning("PDF copy failed ({}): {}", src, e)

        if note_pdfs:
            result.pdfs[source_id] = note_pdfs

        _write_source_state(paths, source_id, note, "inbox", estimated_chars=len(body_md))
        result.source_ids.append(source_id)
        result.new_count += 1

    log.info(
        "Done. notes={} skipped={} errors={}",
        result.new_count,
        result.skipped_count,
        result.error_count,
    )
