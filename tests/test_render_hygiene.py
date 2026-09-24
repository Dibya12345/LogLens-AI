"""Guards against invisible/broken characters in source and rendered output.

A zero-width space (U+200B) previously sat inside HTML/SVG tag names in the
report renderer, so charts and RCA bullet lists silently failed to render.
These tests make that class of defect impossible to reintroduce unnoticed.
"""

import pathlib

from loglens.detection.grouping import template_of
from loglens.detection.turbo import mask_template
from loglens.domain.models import LogEntry
from loglens.infrastructure.output.html_report import render_html_report

_INVISIBLE = ["​", "‌", "‍", "﻿"]

ANOMALIES = [
    LogEntry(level="CRITICAL", service="db", message="replication lag critical 500s"),
    LogEntry(level="ERROR", service="api", message="connection refused to db:5432"),
]


def test_no_zero_width_chars_anywhere_in_source():
    root = pathlib.Path(__file__).resolve().parent.parent / "src"
    offenders = []
    for p in root.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        if any(ch in text for ch in _INVISIBLE):
            offenders.append(str(p.relative_to(root)))
    assert not offenders, f"invisible unicode found in: {offenders}"


def test_rendered_html_has_no_invisible_chars_and_renders_charts():
    html_doc = render_html_report(
        source="x.log",
        total_lines=100,
        anomalies=ANOMALIES,
        level_counts={"CRITICAL": 1, "ERROR": 1},
        rca_markdown="## Summary\n- point one\n- point two",
        rca_meta={"provider": "openai", "model": "gpt-4o-mini", "tokens": 10},
    )
    for ch in _INVISIBLE:
        assert ch not in html_doc
    # tags that were previously broken by U+200B must now be well-formed
    assert "<ul>" in html_doc and "</ul>" in html_doc  # RCA bullet list renders
    assert "<rect" in html_doc  # bar chart rectangles render


def test_mask_tokens_have_no_invisible_chars():
    masked = mask_template("GET /api/v1/users/1234 500 in 12ms uuid 9f1c2d3e-...-x")
    grouped = template_of("error 0xDEADBEEF at 10.0.0.1:8080 took 5ms")
    for ch in _INVISIBLE:
        assert ch not in masked
        assert ch not in grouped
