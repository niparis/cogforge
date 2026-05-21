"""Tests for report model and rendering."""
import json
import pytest
from pathlib import Path

from cogforge.reports import (
    Report,
    ReportSummary,
    ReportChanges,
    ReportItem,
    load_report,
    save_report,
    render_json,
    render_markdown,
)


class TestReportDataclasses:
    def test_summary_defaults(self) -> None:
        s = ReportSummary()
        assert s.sources_seen == 0
        d = s.to_dict()
        assert d["sources_seen"] == 0

    def test_summary_from_dict(self) -> None:
        s = ReportSummary.from_dict({"sources_seen": 5, "sources_failed": 1})
        assert s.sources_seen == 5
        assert s.sources_failed == 1

    def test_item_defaults(self) -> None:
        item = ReportItem(source_id="youtube:abc", action="created", message="New source")
        assert item.source_id == "youtube:abc"
        assert not item.requires_llm_judgment

    def test_changes_defaults(self) -> None:
        c = ReportChanges()
        assert c.files_created == []
        assert c.files_modified == []


class TestReportRoundtrip:
    def test_report_to_dict_and_back(self) -> None:
        report = Report(
            run_id="20260514-sync-test",
            command="sync youtube",
            started_at="2026-05-14T00:00:00Z",
            finished_at="2026-05-14T00:01:00Z",
            status="success",
            summary=ReportSummary(sources_seen=3, sources_created=2),
            changes=ReportChanges(files_created=["inbox/youtube/abc.md"]),
            items=[
                ReportItem(source_id="youtube:abc", action="created", message="Fetched transcript"),
            ],
        )
        d = report.to_dict()
        restored = Report.from_dict(d)
        assert restored.run_id == "20260514-sync-test"
        assert restored.command == "sync youtube"
        assert restored.summary.sources_seen == 3
        assert len(restored.items) == 1


class TestReportRendering:
    def test_render_json(self) -> None:
        report = Report(run_id="test-123", command="status", status="success")
        output = render_json(report)
        data = json.loads(output)
        assert data["run_id"] == "test-123"
        assert data["status"] == "success"

    def test_render_markdown(self) -> None:
        report = Report(
            run_id="test-123",
            command="sync youtube",
            status="success",
            summary=ReportSummary(sources_seen=5, sources_created=2),
            items=[ReportItem(source_id="youtube:abc", action="created", message="New transcript")],
        )
        output = render_markdown(report)
        assert "# Run Report" in output
        assert "test-123" in output
        assert "5" in output  # sources_seen


class TestReportPersistence:
    def test_save_and_load_report(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()

        report = Report(
            run_id="20260514T000000Z-sync-youtube-test",
            command="sync youtube",
            started_at="2026-05-14T00:00:00Z",
            finished_at="2026-05-14T00:01:00Z",
            status="partial",
            summary=ReportSummary(sources_seen=2, sources_failed=1),
        )
        saved = save_report(reports_dir, report)
        assert saved.is_file()
        assert "20260514T000000Z-sync-youtube-test.yaml" in saved.name

        loaded = load_report(reports_dir, "20260514T000000Z-sync-youtube-test")
        assert loaded is not None
        assert loaded.run_id == report.run_id
        assert loaded.status == "partial"
        assert loaded.summary.sources_seen == 2

    def test_load_nonexistent_report(self, tmp_path: Path) -> None:
        result = load_report(tmp_path, "nonexistent-run")
        assert result is None