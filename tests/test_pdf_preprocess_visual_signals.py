"""Unit tests for visual_signals.py."""
import pytest

from cogforge.pdf_preprocess.visual_signals import detect_visual_hints


def test_detect_visual_hints_figure():
    hints = detect_visual_hints("See figure 1 for details.")
    assert "figure" in hints


def test_detect_visual_hints_fig_dot():
    hints = detect_visual_hints("As shown in fig. 3.")
    assert "fig." in hints


def test_detect_visual_hints_multiple():
    hints = detect_visual_hints("The chart and diagram are shown below.")
    assert "chart" in hints
    assert "diagram" in hints
    assert "shown below" in hints


def test_detect_visual_hints_case_insensitive():
    hints = detect_visual_hints("FIGURE 1 shows the WORKFLOW.")
    assert "figure" in hints
    assert "workflow" in hints


def test_detect_visual_hints_no_match():
    hints = detect_visual_hints("This is plain text with no visual terms.")
    assert hints == []


def test_detect_visual_hints_deduplication():
    hints = detect_visual_hints("figure figure figure")
    assert hints.count("figure") == 1


def test_detect_visual_hints_empty_string():
    hints = detect_visual_hints("")
    assert hints == []
