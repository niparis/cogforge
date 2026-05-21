"""Substack connector: sync, discovery, fetch, parse, write."""
from __future__ import annotations

import http.cookiejar
import json
from loguru import logger as log
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from markdownify import markdownify
from slugify import slugify

from cogforge.paths import Paths
from cogforge.state import (
    ContentInfo,
    ExcludedInfo,
    LastError,
    Origin,
    PageIndexInfo,
    RunsInfo,
    SourcePaths,
    SourceState,
    SourceStatus,
    decode_source_id,
    encode_source_id,
    load_state,
    save_state,
)



USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
API_PAGE_SIZE = 50
SLEEP_BETWEEN_POSTS_SEC = 2.0


# ── Substack Post Metadata ────────────────────────────────────────────────────

@dataclass
class PostMeta:
    slug: str
    title: str
    canonical_url: str
    post_date: str = ""
    audience: str = "everyone"
    author: str = ""


# ── Cookie path resolution ────────────────────────────────────────────────────

def _resolve_cookies_path(value: str | None, wiki_root: Path) -> Path | None:
    """Resolve a cookies_txt config value to an absolute Path.

    Absolute paths are used as-is.  Relative paths are tried against the repo
    root (wiki_root.parent) first, then the wiki root itself.  Returns None if
    value is None or no candidate exists on disk.
    """
    if value is None:
        return None
    p = Path(value)
    if p.is_absolute():
        return p if p.exists() else None
    for base in (wiki_root.parent, wiki_root):
        candidate = base / p
        if candidate.exists():
            return candidate
    return None


# ── HTTP Client ───────────────────────────────────────────────────────────────

def build_client(
    cookie_file: Path | None = None,
    cookies_txt: Path | None = None,
) -> httpx.Client:
    """Build the HTTP client for Substack requests."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    jar: http.cookiejar.CookieJar = http.cookiejar.CookieJar()

    if cookies_txt is not None:
        mz = http.cookiejar.MozillaCookieJar(str(cookies_txt))
        mz.load(ignore_discard=True, ignore_expires=True)
        n = 0
        for c in mz:
            jar.set_cookie(c)
            n += 1
        log.info("loaded {} cookies from {}", n, cookies_txt)

    if cookie_file is not None:
        sid = cookie_file.read_text().strip()
        if sid:
            for domain in (".substack.com", ".paperswithbacktest.com"):
                jar.set_cookie(
                    http.cookiejar.Cookie(
                        version=0,
                        name="substack.sid",
                        value=sid,
                        port=None,
                        port_specified=False,
                        domain=domain,
                        domain_specified=True,
                        domain_initial_dot=domain.startswith("."),
                        path="/",
                        path_specified=True,
                        secure=True,
                        expires=None,
                        discard=False,
                        comment=None,
                        comment_url=None,
                        rest={},
                        rfc2109=False,
                    )
                )

    return httpx.Client(
        headers=headers,
        cookies=jar,
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=10.0),
    )


# ── Discovery ─────────────────────────────────────────────────────────────────

def pub_base(publication: str) -> str:
    return f"https://{publication}.substack.com"


def resolve_subdomain(handle_or_subdomain: str, client: httpx.Client) -> str:
    """Resolve a Substack handle to its publication subdomain."""
    r = client.get(f"https://{handle_or_subdomain}.substack.com/", follow_redirects=False)
    if r.status_code == 200:
        return handle_or_subdomain
    profile = client.get(
        f"https://substack.com/api/v1/user/{handle_or_subdomain}/public_profile",
        headers={"Accept": "application/json"},
    )
    if profile.status_code != 200:
        log.warning(
            "could not resolve {} as handle (HTTP {}); using as-is",
            handle_or_subdomain,
            profile.status_code,
        )
        return handle_or_subdomain
    data = profile.json()
    sub = (data.get("primaryPublication") or {}).get("subdomain")
    if not sub:
        log.warning("profile for {} has no primaryPublication.subdomain", handle_or_subdomain)
        return handle_or_subdomain
    log.info("resolved handle {} -> subdomain {}", handle_or_subdomain, sub)
    return sub


def discover(
    publication: str,
    client: httpx.Client,
    seeds_file: Path | None = None,
) -> list[PostMeta]:
    """Return de-duplicated post metadata for a Substack publication."""
    posts: dict[str, PostMeta] = {}

    for strategy in (
        ("archive API", lambda: _from_archive_api(publication, client)),
        ("sitemap", lambda: _from_sitemap(publication, client)),
        ("profile page", lambda: _from_profile(publication, client)),
    ):
        name, fn = strategy
        try:
            found = fn()
            log.info("discovery: {} yielded {} posts", name, len(found))
            for p in found:
                posts.setdefault(p.slug, p)
        except Exception as e:  # noqa: BLE001
            log.warning("discovery: {} failed: {}", name, e)

    if seeds_file is not None and seeds_file.exists():
        seed_posts = _from_seeds(seeds_file)
        log.info("discovery: seeds file yielded {} posts", len(seed_posts))
        for p in seed_posts:
            posts.setdefault(p.slug, p)

    return sorted(posts.values(), key=lambda p: p.post_date, reverse=True)


def _from_archive_api(publication: str, client: httpx.Client) -> list[PostMeta]:
    base = pub_base(publication)
    out: list[PostMeta] = []
    offset = 0
    while True:
        url = f"{base}/api/v1/archive"
        r = client.get(
            url,
            params={"sort": "new", "limit": API_PAGE_SIZE, "offset": offset},
            headers={"Accept": "application/json"},
        )
        if r.status_code != 200:
            raise RuntimeError(f"archive API HTTP {r.status_code} at offset {offset}")
        try:
            items = r.json()
        except ValueError as e:
            raise RuntimeError(f"archive API non-JSON response: {e}") from e
        if not isinstance(items, list) or not items:
            break
        for item in items:
            slug = item.get("slug")
            if not slug:
                continue
            canonical = item.get("canonical_url") or f"{base}/p/{slug}"
            post_date = (item.get("post_date") or "")[:10]
            out.append(
                PostMeta(
                    slug=slug,
                    title=item.get("title") or slug,
                    canonical_url=canonical,
                    post_date=post_date,
                    audience=item.get("audience") or "everyone",
                )
            )
        if len(items) < API_PAGE_SIZE:
            break
        offset += API_PAGE_SIZE
    return out


def _from_sitemap(publication: str, client: httpx.Client) -> list[PostMeta]:
    base = pub_base(publication)
    candidate_urls = [f"{base}/sitemap.xml"]
    out: list[PostMeta] = []
    seen_sub_sitemaps: set[str] = set()

    while candidate_urls:
        url = candidate_urls.pop(0)
        r = client.get(url)
        if r.status_code != 200 or not r.text.strip().startswith("<"):
            continue
        soup = BeautifulSoup(r.text, "xml")
        for loc in soup.select("sitemap > loc"):
            sub = loc.get_text(strip=True)
            if sub and sub not in seen_sub_sitemaps:
                seen_sub_sitemaps.add(sub)
                candidate_urls.append(sub)
        for url_node in soup.select("url"):
            loc = url_node.find("loc")
            if not loc:
                continue
            link = loc.get_text(strip=True)
            m = re.search(r"/p/([^/?#]+)", link)
            if not m:
                continue
            slug = m.group(1)
            lastmod = url_node.find("lastmod")
            post_date = (lastmod.get_text(strip=True)[:10] if lastmod else "")
            out.append(
                PostMeta(
                    slug=slug,
                    title=slug,
                    canonical_url=link,
                    post_date=post_date,
                )
            )
    return out


def _from_profile(publication: str, client: httpx.Client) -> list[PostMeta]:
    url = f"https://substack.com/@{publication}"
    r = client.get(url)
    if r.status_code != 200:
        raise RuntimeError(f"profile HTTP {r.status_code}")
    out: list[PostMeta] = []
    for m in re.finditer(
        r'https?://[a-z0-9.-]*substack\.com/p/([a-z0-9-]+)', r.text, re.IGNORECASE
    ):
        slug = m.group(1).lower()
        canonical = m.group(0)
        out.append(
            PostMeta(
                slug=slug,
                title=slug,
                canonical_url=canonical,
            )
        )
    return out


def _from_seeds(seeds_file: Path) -> list[PostMeta]:
    out: list[PostMeta] = []
    for raw_line in seeds_file.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.search(r"/p/([^/?#]+)", line)
        if not m:
            continue
        slug = m.group(1)
        out.append(PostMeta(slug=slug, title=slug, canonical_url=line))
    return out


# ── Parser ────────────────────────────────────────────────────────────────────

@dataclass
class ParsedPost:
    title: str
    author: str
    date_published: str  # YYYY-MM-DD
    body_html: str
    image_urls: list[str] = field(default_factory=list)
    is_paywalled_body: bool = False


def parse_post_page(html: str) -> ParsedPost:
    soup = BeautifulSoup(html, "lxml")

    title = _meta(soup, "og:title") or _text(soup.select_one("h1")) or ""
    author = _meta(soup, "author") or _meta(soup, "article:author") or ""
    raw_date = _meta(soup, "article:published_time") or ""
    date_published = raw_date[:10] if raw_date else ""

    body = (
        soup.select_one("div.available-content")
        or soup.select_one("div.body.markup")
        or soup.select_one("article div.post")
        or soup.select_one("article")
    )

    if body is None:
        return ParsedPost(
            title=title,
            author=author,
            date_published=date_published,
            body_html="",
            is_paywalled_body=True,
        )

    for tag in body.select("script, style, noscript"):
        tag.decompose()
    for tag in body.select("div.subscription-widget-wrap, div.subscribe-widget, div.paywall"):
        tag.decompose()

    body_word_count = len(body.get_text(" ", strip=True).split())
    is_paywalled = body_word_count < 80

    image_urls = _collect_image_urls(body)

    return ParsedPost(
        title=title,
        author=author,
        date_published=date_published,
        body_html=str(body),
        image_urls=image_urls,
        is_paywalled_body=is_paywalled,
    )


def rewrite_image_srcs(body_html: str, mapping: dict[str, str]) -> str:
    """Replace remote image URLs with local relative paths."""
    soup = BeautifulSoup(body_html, "lxml")
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src in mapping:
            img["src"] = mapping[src]
            img.attrs.pop("srcset", None)
            img.attrs.pop("data-attrs", None)
    for source in soup.find_all("source"):
        source.decompose()
    return str(soup)


def html_to_markdown(body_html: str) -> str:
    return markdownify(
        body_html,
        heading_style="ATX",
        strip=["script", "style"],
    ).strip()


def _meta(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("meta", attrs={"property": name}) or soup.find(
        "meta", attrs={"name": name}
    )
    if isinstance(tag, Tag):
        content = tag.get("content")
        if isinstance(content, str):
            return content.strip()
    return ""


def _text(tag: Tag | None) -> str:
    return tag.get_text(strip=True) if tag is not None else ""


_CDN_FETCH_RE = re.compile(
    r"^https?://substackcdn\.com/image/fetch/[^/]+/(?P<inner>https?%3A%2F%2F[^/?#]+.*)$"
)


def unwrap_cdn_url(url: str) -> str:
    """Substack image-fetch URLs wrap the real URL — pull it out when possible."""
    m = _CDN_FETCH_RE.match(url)
    if not m:
        return url
    return unquote(m.group("inner"))


def _collect_image_urls(body: Tag) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for img in body.find_all("img"):
        src = img.get("src")
        if isinstance(src, str) and src and src not in seen:
            seen.add(src)
            urls.append(src)
    return urls


# ── Images ────────────────────────────────────────────────────────────────────

def download_images(
    image_urls: list[str],
    dest_dir: Path,
    client: httpx.Client,
) -> dict[str, str]:
    """Download each image and return {original_url: relative_path_from_issue_root}."""
    if not image_urls:
        return {}
    dest_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    for idx, url in enumerate(image_urls, start=1):
        try:
            fetch_url = unwrap_cdn_url(url)
            r = client.get(fetch_url)
            if r.status_code != 200 or not r.content:
                log.warning("image {}: HTTP {}", url, r.status_code)
                continue
            ext = _pick_extension(fetch_url, r.headers.get("content-type", ""))
            stem = _filename_stem(fetch_url)
            filename = f"{idx:03d}-{stem}{ext}"
            (dest_dir / filename).write_bytes(r.content)
            mapping[url] = f"images/{filename}"
        except Exception as e:  # noqa: BLE001
            log.warning("image {} failed: {}", url, e)
    return mapping


def _pick_extension(url: str, content_type: str) -> str:
    parsed = urlparse(url)
    _, ext = os.path.splitext(parsed.path)
    ext = ext.lower()
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif"}:
        return ext
    import mimetypes

    guess = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    return guess if guess else ".bin"


def _filename_stem(url: str) -> str:
    parsed = urlparse(url)
    base = os.path.basename(parsed.path) or "image"
    stem, _ = os.path.splitext(base)
    safe = slugify(stem, max_length=48) or "image"
    return safe


# ── Papers (PDF download) ────────────────────────────────────────────────────

_DIRECT_PDF_RE = re.compile(
    r'https?://[^\s)\]"\']+\.pdf(?=[^\w]|$)',
    re.IGNORECASE,
)
_ARXIV_ABS_RE = re.compile(
    r'https?://arxiv\.org/abs/([\w.]+)',
    re.IGNORECASE,
)
# Substack image proxy URLs — not real PDFs
_IMAGE_PROXY_RE = re.compile(
    r'https?://substackcdn\.com/image/',
    re.IGNORECASE,
)
# Substack attachment download links — actual file downloads
_ATTACHMENT_RE = re.compile(
    r'https?://[a-z0-9.-]+\.substack\.com/api/v1/file/[^\s)\]"\']+',
    re.IGNORECASE,
)


def extract_pdf_urls(markdown_text: str) -> list[str]:
    """Return deduplicated list of downloadable PDF URLs found in Markdown body."""
    seen: set[str] = set()
    urls: list[str] = []

    for m in _DIRECT_PDF_RE.finditer(markdown_text):
        url = m.group(0).rstrip(").,;:'\"").rstrip(")")
        # Skip Substack image proxy URLs (not real PDFs)
        if _IMAGE_PROXY_RE.search(url):
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)

    for m in _ARXIV_ABS_RE.finditer(markdown_text):
        arxiv_id = m.group(1)
        resolved = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        if resolved not in seen:
            seen.add(resolved)
            urls.append(resolved)

    # Substack attachment download links (may redirect to actual file)
    for m in _ATTACHMENT_RE.finditer(markdown_text):
        url = m.group(0).rstrip(").,;:'\"")
        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


def download_pdfs(
    pdf_urls: list[str],
    dest_dir: Path,
    client: httpx.Client,
) -> tuple[int, int]:
    """Download each PDF URL into dest_dir, skipping already-present files."""
    if not pdf_urls:
        return 0, 0

    dest_dir.mkdir(parents=True, exist_ok=True)
    new_count = 0
    skipped_count = 0

    for url in pdf_urls:
        filename = _pdf_filename(url)
        dest = dest_dir / filename

        if dest.exists():
            skipped_count += 1
            continue

        try:
            r = client.get(url, follow_redirects=True)
            if r.status_code != 200 or not r.content:
                log.warning("[PDF-FAIL] {}  HTTP {}", url, r.status_code)
                continue
            ct = r.headers.get("content-type", "")
            if "html" in ct and b"%PDF" not in r.content[:8]:
                log.warning("[PDF-FAIL] {}  got HTML, not PDF", url)
                continue
            dest.write_bytes(r.content)
            log.info("[PDF] {}  -> {} ({} KB)", url, filename, len(r.content) // 1024)
            new_count += 1
            time.sleep(1.0)
        except Exception as e:  # noqa: BLE001
            log.warning("[PDF-FAIL] {}  {}", url, e)

    return new_count, skipped_count


def _pdf_filename(url: str) -> str:
    parsed = urlparse(url)
    name = os.path.basename(parsed.path) or "paper.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    name = re.sub(r'[^\w.\-]', '_', name)
    return name


# ── Writer (issue packaging) ──────────────────────────────────────────────────

def newsletter_slug(newsletter: str) -> str:
    """Sanitize newsletter name for filesystem-safe directory name."""
    return slugify(newsletter, max_length=48, lowercase=False) or "newsletter"


def issue_dirname(meta: PostMeta) -> str:
    prefix = meta.post_date if meta.post_date else "0000-00-00"
    return f"{prefix}-{meta.slug}"


def issue_dir(out_dir: Path, meta: PostMeta) -> Path:
    return out_dir / issue_dirname(meta)


def already_done(out_dir: Path, meta: PostMeta) -> bool:
    return (issue_dir(out_dir, meta) / "index.md").exists()



def _already_synced_on_disk(
    paths: Paths,
    ns_slug: str,
    meta: PostMeta,
    synced_keys: set[str] | None = None,
) -> bool:
    """Check if a post already exists in inbox or raw on disk.

    Uses newsletter_slug/post_slug as the compound key.
    If synced_keys is provided, uses that precomputed set.
    """
    key = f"{ns_slug}/{meta.slug}"
    if synced_keys is not None:
        return key in synced_keys

    for base in (paths.connector_inbox("substack"), paths.connector_raw("substack")):
        if already_done(base / ns_slug, meta):
            return True
    return False


def _build_synced_substack_ids(paths: Paths) -> set[str]:
    """Build set of 'newsletter_slug/post_slug' keys already synced to disk."""
    synced: set[str] = set()
    for base in (paths.connector_inbox("substack"), paths.connector_raw("substack")):
        if not base.is_dir():
            continue
        for ns_dir in base.iterdir():
            if not ns_dir.is_dir():
                continue
            for folder in ns_dir.iterdir():
                if folder.is_dir() and (folder / "index.md").exists():
                    parts = folder.name.split("-", 3)
                    if len(parts) >= 4:
                        synced.add(f"{ns_dir.name}/{parts[3]}")
    return synced


def write_issue(
    out_dir: Path,
    meta: PostMeta,
    publication: str,
    newsletter: str,
    body_markdown: str,
    body_html: str,
    paywalled_body: bool,
    resolved_title: str,
    resolved_author: str,
    resolved_date: str,
) -> Path:
    """Write index.md and original.html into the issue folder. Returns folder."""
    from datetime import date

    folder = issue_dir(out_dir, meta)
    folder.mkdir(parents=True, exist_ok=True)

    frontmatter: dict[str, Any] = {
        "source": meta.canonical_url,
        "publication": publication,
        "newsletter": newsletter,
        "title": resolved_title or meta.title,
        "author": resolved_author,
        "date_published": resolved_date or meta.post_date,
        "date_fetched": date.today().isoformat(),
        "slug": meta.slug,
        "audience": meta.audience,
        "paywalled_body": paywalled_body,
        "language": "en",
    }
    import yaml

    fm = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()

    md_text = f"---\n{fm}\n---\n\n# {frontmatter['title']}\n\n{body_markdown}\n"
    (folder / "index.md").write_text(md_text, encoding="utf-8")
    (folder / "original.html").write_text(body_html, encoding="utf-8")
    return folder


# ── Sync Orchestration ────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    """Result of a sync operation."""

    publication: str
    connector: str = "substack"
    new_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    total_discovered: int = 0
    source_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _sync_publication(
    publication: str,
    newsletter: str,
    paths: Paths,
    *,
    source_id: str | None = None,
    max_posts: int | None = None,
    refresh_index: bool = False,
    cookies_txt: Path | None = None,
    cookie_file: Path | None = None,
    skip_pdfs: bool = False,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> SyncResult:
    """Sync a single Substack publication into the wiki inbox."""
    result = SyncResult(publication=publication)

    # Build HTTP client
    client = build_client(cookie_file=cookie_file, cookies_txt=cookies_txt)

    try:
        # Resolve subdomain
        subdomain = resolve_subdomain(publication, client)

        # Compute newsletter subdirectory
        ns_slug = newsletter_slug(newsletter)
        inbox_ns_dir = paths.connector_inbox("substack") / ns_slug
        raw_ns_dir = paths.connector_raw("substack") / ns_slug

        # Discover posts
        index_path = inbox_ns_dir / "_index.json"
        posts = _resolve_index(subdomain, client, index_path, refresh_index, log)

        if not posts:
            log.error("no posts discovered")
            result.errors.append("No posts discovered for publication")
            return result

        result.total_discovered = len(posts)
        log.info("known posts: {}", len(posts))

        if dry_run:
            for p in posts[:max_posts or len(posts)]:
                log.info(
                    "DRY RUN: {}  {}  {}",
                    p.post_date or "----------",
                    p.audience,
                    p.canonical_url,
                )
            result.source_ids = [p.slug for p in posts[:max_posts or len(posts)]]
            return result

        # Process posts
        new_count = 0
        skipped = 0
        errors = 0

        # Build set of already-synced post keys (newsletter_slug/post_slug)
        synced_keys = _build_synced_substack_ids(paths)
        if verbose:
            log.info("Already synced on disk: {} posts", len(synced_keys))

        for meta in posts:
            if max_posts is not None and new_count >= max_posts:
                break

            # If source_id is specified, only sync that one
            if source_id is not None and meta.slug != source_id:
                continue

            # Check state file for processed/excluded status
            source_id_str = f"substack:{meta.slug}"
            existing_state = load_state(paths.state_sources, source_id_str)
            if existing_state and existing_state.status in (SourceStatus.PROCESSED.value, SourceStatus.EXCLUDED.value):
                skipped += 1
                if verbose:
                    log.info("Skipping (state={}): {}", existing_state.status, meta.slug)
                continue

            # Check disk (inbox + raw)
            if _already_synced_on_disk(paths, ns_slug, meta, synced_keys):
                if force:
                    log.info("[FORCE] re-fetching {}", meta.slug)
                    # fall through to _process_post to re-fetch with cookies
                else:
                    skipped += 1
                    if not skip_pdfs:
                        _sync_pdfs(meta, inbox_ns_dir, client, log, raw_dir=raw_ns_dir)
                    if verbose:
                        log.info("Skipping already-synced (disk): {}", meta.slug)
                    continue

            try:
                _process_post(
                    meta=meta,
                    publication=publication,
                    subdomain=subdomain,
                    newsletter=newsletter,
                    out_dir=inbox_ns_dir,
                    client=client,
                    skip_pdfs=skip_pdfs,
                )

                # Write source state
                _write_source_state(paths, source_id_str, meta, "inbox", newsletter=newsletter)
                result.source_ids.append(source_id_str)
                new_count += 1
            except Exception as e:  # noqa: BLE001
                log.error("[FAIL] {}: {}", meta.slug, e)
                result.errors.append(f"{meta.slug}: {e}")
                errors += 1
                # Write failed state
                _write_source_state(
                    paths, source_id_str, meta, "failed", newsletter=newsletter, error=str(e)
                )
                time.sleep(SLEEP_BETWEEN_POSTS_SEC)

        result.new_count = new_count
        result.skipped_count = skipped
        result.error_count = errors
        log.info(
            "done. new={} skipped={} errors={} total={}",
            new_count,
            skipped,
            errors,
            len(posts),
        )
        return result
    finally:
        client.close()


def sync_substack(
    publication: str,
    newsletter: str,
    paths: Paths,
    config: Any,
    *,
    source_id: str | None = None,
    all_sources: bool = False,
    max_posts: int | None = None,
    refresh_index: bool = False,
    cookies_txt: Path | None = None,
    cookie_file: Path | None = None,
    skip_pdfs: bool = False,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> SyncResult:
    """Sync Substack publication(s) into the wiki inbox.

    When all_sources=True, iterates all enabled substack entries from config,
    using per-source cookies_txt when available.  Otherwise syncs the single
    publication specified by publication/newsletter, auto-loading cookies_txt
    from config when the caller does not supply it explicitly.

    force=True re-fetches posts whose on-disk index.md is a
    paywalled stub (paywalled_body: true), so they can be upgraded to full
    content when cookies are now available.
    """
    from cogforge.config import Config

    cfg = config if isinstance(config, Config) else Config()

    if all_sources:
        aggregated = SyncResult(publication="")
        pub_names: list[str] = []
        for src in cfg.sources.get("substack", []):
            if not src.enabled or not src.publication:
                continue
            resolved_cookies = cookies_txt or _resolve_cookies_path(src.cookies_txt, paths.root)
            log.info("syncing source={} publication={}", src.id, src.publication)
            r = _sync_publication(
                publication=src.publication,
                newsletter=src.newsletter or src.publication,
                paths=paths,
                source_id=source_id,
                max_posts=max_posts,
                refresh_index=refresh_index,
                cookies_txt=resolved_cookies,
                cookie_file=cookie_file,
                skip_pdfs=skip_pdfs,
                force=force,
                dry_run=dry_run,
                verbose=verbose,
            )
            pub_names.append(src.publication)
            aggregated.new_count += r.new_count
            aggregated.skipped_count += r.skipped_count
            aggregated.error_count += r.error_count
            aggregated.total_discovered += r.total_discovered
            aggregated.source_ids.extend(r.source_ids)
            aggregated.errors.extend(r.errors)
        aggregated.publication = ", ".join(pub_names) if pub_names else "(none)"
        return aggregated

    # Single-publication mode: auto-load cookies from config when not explicit.
    effective_cookies = cookies_txt
    if effective_cookies is None:
        for src in cfg.sources.get("substack", []):
            if src.publication == publication:
                effective_cookies = _resolve_cookies_path(src.cookies_txt, paths.root)
                if effective_cookies:
                    log.info("auto-loaded cookies from config: {}", effective_cookies)
                break

    return _sync_publication(
        publication=publication,
        newsletter=newsletter,
        paths=paths,
        source_id=source_id,
        max_posts=max_posts,
        refresh_index=refresh_index,
        cookies_txt=effective_cookies,
        cookie_file=cookie_file,
        skip_pdfs=skip_pdfs,
        force=force,
        dry_run=dry_run,
        verbose=verbose,
    )


def _resolve_index(
    subdomain: str,
    client: httpx.Client,
    index_path: Path,
    refresh: bool,
    log: logging.Logger,
) -> list[PostMeta]:
    if not refresh:
        cached = _load_index(index_path)
        if cached:
            log.info("using cached index: {} ({} posts)", index_path, len(cached))
            return cached
    log.info("discovering posts for subdomain={} ...", subdomain)
    posts = discover(subdomain, client)
    if posts:
        _save_index(index_path, posts)
        log.info("saved index: {} ({} posts)", index_path, len(posts))
    return posts


def _load_index(path: Path) -> list[PostMeta]:
    """Load cached post index from JSON."""
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    return [PostMeta(**item) for item in raw]


def _save_index(path: Path, posts: list[PostMeta]) -> None:
    """Save post index to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(p) for p in posts], indent=2, ensure_ascii=False)
    )


def _sync_pdfs(
    meta: PostMeta,
    out_dir: Path,
    client: httpx.Client,
    log: logging.Logger,
    *,
    raw_dir: Path | None = None,
) -> None:
    """Download any PDFs linked from an already-archived article.

    Checks out_dir first (inbox), then raw_dir if provided.
    """
    for base in (out_dir, raw_dir):
        if base is None:
            continue
        folder = issue_dir(base, meta)
        md_path = folder / "index.md"
        if md_path.exists():
            pdf_urls = extract_pdf_urls(md_path.read_text())
            if pdf_urls:
                download_pdfs(pdf_urls, folder / "papers", client)
            return


def _process_post(
    meta: PostMeta,
    publication: str,
    subdomain: str,
    newsletter: str,
    out_dir: Path,
    client: httpx.Client,
    skip_pdfs: bool = False,
) -> None:
    """Fetch, parse, and write one post as a source package."""
    url = meta.canonical_url or f"{pub_base(subdomain)}/p/{meta.slug}"
    log.info("[FETCH] {}", url)
    r = client.get(url)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")

    parsed = parse_post_page(r.text)
    paywalled = parsed.is_paywalled_body

    if paywalled:
        log.info("[PAYWALL] {} — saving stub", meta.slug)
        write_issue(
            out_dir=out_dir,
            meta=meta,
            publication=publication,
            newsletter=newsletter,
            body_markdown=(
                "_This post is paywalled. Subscribe and rerun with `--cookies-txt` "
                "to archive the full body._"
            ),
            body_html=parsed.body_html or "",
            paywalled_body=True,
            resolved_title=parsed.title,
            resolved_author=parsed.author,
            resolved_date=parsed.date_published,
        )
        return

    images_dir = issue_dir(out_dir, meta) / "images"
    image_mapping = download_images(parsed.image_urls, images_dir, client)
    rewritten_html = rewrite_image_srcs(parsed.body_html, image_mapping)
    body_md = html_to_markdown(rewritten_html)

    write_issue(
        out_dir=out_dir,
        meta=meta,
        publication=publication,
        newsletter=newsletter,
        body_markdown=body_md,
        body_html=rewritten_html,
        paywalled_body=False,
        resolved_title=parsed.title,
        resolved_author=parsed.author,
        resolved_date=parsed.date_published,
    )
    log.info("[NEW] {}  ({} images)", meta.slug, len(image_mapping))

    if not skip_pdfs:
        pdf_urls = extract_pdf_urls(body_md)
        download_pdfs(pdf_urls, issue_dir(out_dir, meta) / "papers", client)


def _write_source_state(
    paths: Paths,
    source_id: str,
    meta: PostMeta,
    status: str,
    *,
    newsletter: str = "",
    error: str | None = None,
) -> None:
    """Write source state YAML after sync."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    ns_slug = newsletter_slug(newsletter) if newsletter else ""
    inbox_path = f"inbox/substack/{ns_slug}/{issue_dirname(meta)}" if ns_slug else f"inbox/substack/{issue_dirname(meta)}"
    state = SourceState(
        version=1,
        id=source_id,
        connector="substack",
        status=status,
        origin=Origin(
            url=meta.canonical_url,
            title=meta.title,
            fetched_at=now,
        ),
        content=ContentInfo(),
        paths=SourcePaths(
            inbox=inbox_path,
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