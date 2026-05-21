"""Tests for the Substack sync module (Sprint 2)."""
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cogforge.sync import (
    PostMeta,
    ParsedPost,
    SyncResult,
    _filename_stem,
    _from_seeds,
    _pdf_filename,
    already_done,
    build_client,
    discover,
    extract_pdf_urls,
    html_to_markdown,
    issue_dir,
    issue_dirname,
    resolve_subdomain,
    sync_substack,
    unwrap_cdn_url,
    write_issue,
)
from cogforge.state import load_state


def _parse_frontmatter(md_text: str) -> dict:
    """Extract YAML frontmatter from Markdown text."""
    m = re.match(r'^---\s*\n(.*?)\n---', md_text, re.DOTALL)
    if not m:
        return {}
    import yaml
    return yaml.safe_load(m.group(1))


class TestPostMeta:
    def test_minimal(self):
        meta = PostMeta(slug="test", title="Test", canonical_url="https://example.com/p/test")
        assert meta.slug == "test"
        assert meta.title == "Test"
        assert meta.canonical_url == "https://example.com/p/test"

    def test_full(self):
        meta = PostMeta(
            slug="my-post", title="My Post", canonical_url="https://x.com/p/my-post",
            post_date="2026-05-14", audience="subscribers-only", author="Jane Doe",
        )
        assert meta.post_date == "2026-05-14"
        assert meta.audience == "subscribers-only"


class TestSyncResult:
    def test_default(self):
        result = SyncResult(publication="test")
        assert result.publication == "test"
        assert result.connector == "substack"
        assert result.new_count == 0
        assert result.source_ids == []

    def test_with_values(self):
        result = SyncResult(publication="test", new_count=5, skipped_count=3,
                            error_count=1, total_discovered=10, source_ids=["a", "b"], errors=["err1"])
        assert result.new_count == 5
        assert result.error_count == 1


class TestIssueDir:
    def test_dirname_with_date(self):
        meta = PostMeta(slug="my-post", title="T", canonical_url="https://x.com/p/my-post", post_date="2026-05-14")
        assert issue_dirname(meta) == "2026-05-14-my-post"

    def test_dirname_no_date(self):
        meta = PostMeta(slug="my-post", title="T", canonical_url="https://x.com/p/my-post")
        assert issue_dirname(meta) == "0000-00-00-my-post"

    def test_issue_dir(self, tmp_path):
        meta = PostMeta(slug="my-post", title="T", canonical_url="https://x.com/p/my-post", post_date="2026-05-14")
        assert issue_dir(tmp_path, meta) == tmp_path / "2026-05-14-my-post"


class TestAlreadyDone:
    def test_not_done(self, tmp_path):
        meta = PostMeta(slug="my-post", title="T", canonical_url="https://x.com/p/my-post")
        assert not already_done(tmp_path, meta)

    def test_done(self, tmp_path):
        meta = PostMeta(slug="my-post", title="T", canonical_url="https://x.com/p/my-post")
        d = issue_dir(tmp_path, meta)
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.md").write_text("# test")
        assert already_done(tmp_path, meta)


class TestBuildClient:
    def test_default_client(self):
        client = build_client()
        assert client is not None
        assert "User-Agent" in client.headers
        client.close()

    def test_client_with_cookies_txt(self, tmp_path):
        cookie_file = tmp_path / "cookies.txt"
        cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            ".substack.com\tTRUE\t/\tFALSE\t0\tsubstack.sid\ttest123\n"
        )
        client = build_client(cookies_txt=cookie_file)
        assert client is not None
        client.close()


class TestResolveSubdomain:
    def test_handles_invalid_handle(self):
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 404
        client.get.return_value = resp
        result = resolve_subdomain("definitely-not-a-real-handle-xyz", client)
        assert result == "definitely-not-a-real-handle-xyz"


class TestDiscover:
    def test_empty_publication_no_crash(self):
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 404
        client.get.return_value = resp
        result = discover("nonexistent", client)
        assert result == []


class TestParsePostPage:
    def test_paywalled_body(self):
        """Content with < 80 words in the available-content div is paywalled."""
        from cogforge.sync import parse_post_page
        html = """<html><body>
        <div class="available-content">
            <h1>Short Post</h1>
            <p>Only a few words here.</p>
        </div>
        </body></html>"""
        parsed = parse_post_page(html)
        assert parsed.is_paywalled_body is True
        assert parsed.title == "Short Post"
        # Body HTML is still set (not empty) when paywalled - it's just an empty string
        # because the body class matched
        assert parsed.body_html != ""  # body HTML is captured

    def test_long_body_not_paywalled(self):
        """Body with many words should not be paywalled."""
        from cogforge.sync import parse_post_page
        long_text = "word " * 50  # 200+ words total across paragraphs
        html = f"""<html><body>
        <article>
            <h1>Long Post</h1>
            <div class="body markup">
                <p>{long_text}</p>
                <p>{'word ' * 50}more content here beyond the threshold.</p>
            </div>
        </article>
        </body></html>"""
        parsed = parse_post_page(html)
        assert parsed.is_paywalled_body is False
        assert parsed.title == "Long Post"

    def test_body_without_content_div(self):
        """HTML without content div should be paywalled."""
        from cogforge.sync import parse_post_page
        html = "<html><body><p>Just some text</p></body></html>"
        parsed = parse_post_page(html)
        assert parsed.is_paywalled_body is True


class TestUnwrapCdnUrl:
    def test_unwrap_cdn_url(self):
        url = "https://substackcdn.com/image/fetch/f_auto,fl_progressive,q_auto:good,w_600/https%3A%2F%2Fsubstack-post-media.s3.amazonaws.com%2Fpublic%2Fimages%2Fabc123.png"
        result = unwrap_cdn_url(url)
        assert "substackcdn.com" not in result
        assert "abc123.png" in result

    def test_unwrap_non_cdn_url(self):
        url = "https://example.com/image.png"
        assert unwrap_cdn_url(url) == url


class TestPdfExtraction:
    def test_extract_direct_pdf_urls(self):
        md = "Check this [paper](https://example.com/research.pdf) out."
        urls = extract_pdf_urls(md)
        assert "https://example.com/research.pdf" in urls

    def test_extract_arxiv_urls(self):
        md = "See [arxiv](https://arxiv.org/abs/2301.12345) for details."
        urls = extract_pdf_urls(md)
        assert "https://arxiv.org/pdf/2301.12345.pdf" in urls

    def test_extract_no_urls(self):
        urls = extract_pdf_urls("No PDFs here, just text.")
        assert urls == []

    def test_extract_deduplicates(self):
        md = "Link [a](https://example.com/paper.pdf) and [b](https://example.com/paper.pdf)."
        urls = extract_pdf_urls(md)
        assert len(urls) == 1


class TestPdfFilename:
    def test_simple_url(self):
        assert _pdf_filename("https://example.com/paper.pdf") == "paper.pdf"

    def test_url_without_extension(self):
        assert _pdf_filename("https://example.com/paper") == "paper.pdf"

    def test_special_chars_sanitized(self):
        result = _pdf_filename("https://example.com/my file@name!.pdf")
        assert " " not in result
        assert result.endswith(".pdf")


class TestWriter:
    def test_write_issue_creates_files(self, tmp_path):
        meta = PostMeta(
            slug="test-post", title="Test Post",
            canonical_url="https://example.com/p/test-post",
            post_date="2026-05-14", audience="everyone",
        )
        out_dir = tmp_path / "outbox" / "substack"
        result = write_issue(
            out_dir=out_dir, meta=meta, publication="paperswithbacktest",
            newsletter="Algo Trading & AI",
            body_markdown="Test content here.",
            body_html="<h1>Test Post</h1><p>Content here.</p>",
            paywalled_body=False,
            resolved_title="Test Post", resolved_author="Author", resolved_date="2026-05-14",
        )

        assert result == out_dir / "2026-05-14-test-post"
        assert (result / "index.md").exists()
        assert (result / "original.html").exists()

        content = (result / "index.md").read_text()
        fm = _parse_frontmatter(content)
        assert fm["title"] == "Test Post"
        assert fm["publication"] == "paperswithbacktest"
        assert "slug" in fm

    def test_write_paywalled_issue(self, tmp_path):
        meta = PostMeta(slug="paywalled-post", title="Paywalled", canonical_url="https://example.com/p/paywalled-post")
        out_dir = tmp_path / "outbox" / "substack"
        write_issue(
            out_dir=out_dir, meta=meta, publication="testpub",
            newsletter="Test Newsletter",
            body_markdown="_This post is paywalled._",
            body_html="<p>paywall notice</p>",
            paywalled_body=True, resolved_title="Paywalled", resolved_author="", resolved_date="",
        )
        md_files = list(out_dir.rglob("index.md"))
        assert len(md_files) >= 1
        content = md_files[0].read_text()
        assert "paywalled" in content.lower()


class TestSyncSubstack:
    def _mock_response(self, status_code=200, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text
        return resp

    def test_dry_run_returns_no_errors(self, tmp_path):
        inbox_dir = tmp_path / "inbox" / "substack"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        state_dir = tmp_path / ".llmkb" / "state" / "sources"
        state_dir.mkdir(parents=True, exist_ok=True)

        fake_posts = [
            PostMeta(slug="test-post-1", title="Test Post 1",
                     canonical_url="https://substack.com/p/test-post-1", post_date="2026-05-10"),
            PostMeta(slug="test-post-2", title="Test Post 2",
                     canonical_url="https://substack.com/p/test-post-2", post_date="2026-05-09"),
        ]

        cfg = MagicMock()

        with patch("cogforge.sync.resolve_subdomain", return_value="substack"):
            with patch("cogforge.sync.discover", return_value=fake_posts):
                paths = MagicMock()
                paths.state_sources = state_dir
                paths.connector_inbox.return_value = inbox_dir

                result = sync_substack(
                    publication="substack", newsletter="Test Newsletter",
                    paths=paths, config=cfg, dry_run=True,
                )

                assert result.total_discovered == 2
                assert result.new_count == 0
                assert result.error_count == 0
                assert len(result.source_ids) == 2

    def test_sync_creates_state_files(self, tmp_path):
        inbox_dir = tmp_path / "inbox" / "substack"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        state_dir = tmp_path / ".llmkb" / "state" / "sources"
        state_dir.mkdir(parents=True, exist_ok=True)

        fake_posts = [
            PostMeta(slug="test-post-1", title="Test Post 1",
                     canonical_url="https://substack.com/p/test-post-1",
                     post_date="2026-05-10", audience="everyone"),
        ]

        cfg = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = self._mock_response(200, "<html></html>")

        with patch("cogforge.sync.resolve_subdomain", return_value="substack"):
            with patch("cogforge.sync.discover", return_value=fake_posts):
                with patch("cogforge.sync.build_client", return_value=mock_client):
                    paths = MagicMock()
                    paths.state_sources = state_dir
                    paths.connector_inbox.return_value = inbox_dir

                    result = sync_substack(
                        publication="substack", newsletter="Test",
                        paths=paths, config=cfg, dry_run=False, skip_pdfs=True,
                    )

                    assert result.new_count == 1
                    assert result.error_count == 0

                    state_files = list(state_dir.glob("*.yaml"))
                    assert len(state_files) == 1

                    state = load_state(state_dir, "substack:test-post-1")
                    assert state is not None
                    assert state.id == "substack:test-post-1"
                    assert state.connector == "substack"
                    assert state.status == "inbox"

    def test_sync_with_failed_post_creates_failed_state(self, tmp_path):
        inbox_dir = tmp_path / "inbox" / "substack"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        state_dir = tmp_path / ".llmkb" / "state" / "sources"
        state_dir.mkdir(parents=True, exist_ok=True)

        fake_posts = [
            PostMeta(slug="bad-post", title="Bad",
                     canonical_url="https://substack.com/p/bad-post", audience="everyone"),
        ]

        cfg = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = self._mock_response(200, "<html></html>")

        with patch("cogforge.sync.resolve_subdomain", return_value="substack"):
            with patch("cogforge.sync.discover", return_value=fake_posts):
                with patch("cogforge.sync.build_client", return_value=mock_client):
                    # Mock write_issue to raise an error
                    with patch("cogforge.sync.write_issue", side_effect=RuntimeError("HTTP 404")):
                        paths = MagicMock()
                        paths.state_sources = state_dir
                        paths.connector_inbox.return_value = inbox_dir

                        result = sync_substack(
                            publication="substack", newsletter="Test",
                            paths=paths, config=cfg, dry_run=False, skip_pdfs=True,
                        )

                        assert result.error_count == 1
                        assert "bad-post" in result.errors[0]


class TestSyncResultJSON:
    def test_sync_result_is_json_serializable(self):
        result = SyncResult(publication="test", new_count=5, source_ids=["a", "b"], errors=["err1"])
        data = {
            "publication": result.publication, "connector": result.connector,
            "total_discovered": result.total_discovered, "new_count": result.new_count,
            "skipped_count": result.skipped_count, "error_count": result.error_count,
            "source_ids": result.source_ids, "errors": result.errors,
        }
        json.dumps(data)


class TestCLIIntegration:
    def test_sync_group_exists(self):
        from click.testing import CliRunner
        from cogforge.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["sync", "--help"])
        assert result.exit_code == 0
        assert "substack" in result.output

    def test_sync_substack_help(self):
        from click.testing import CliRunner
        from cogforge.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["sync", "substack", "--help"])
        assert result.exit_code == 0
        assert "--publication" in result.output
        assert "--all-sources" in result.output
        assert "--source-id" in result.output
        assert "--max" in result.output