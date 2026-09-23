from __future__ import annotations

import pytest

from loglens.domain.scoring import (
    REASON_CODES,
    Signals,
    score,
    threshold_for,
)

GOLDEN: dict[str, tuple[Signals, float, list[str]]] = {
    "fatal_hard_flag": (
        Signals(level="FATAL", message="kernel panic"),
        0.9667,
        ["hard_flag", "rare", "catastrophe"],
    ),
    "critical_rare_failure": (
        Signals(
            level="CRITICAL",
            message="connection refused",
            template_count=1,
            level_total=354,
            file_total=2009,
        ),
        0.9468,
        ["severity", "rare", "failure"],
    ),
    "error_with_failure_keyword": (
        Signals(
            level="ERROR",
            message="timeout",
            template_count=400,
            level_total=800,
            file_total=2009,
        ),
        0.77,
        ["severity", "failure"],
    ),
    "info_benign": (
        Signals(
            level="INFO",
            message="request ok",
            template_count=900,
            level_total=1500,
            file_total=2009,
        ),
        0.0,
        [],
    ),
    "warning_flood": (
        Signals(
            level="WARNING",
            message="retrying",
            template_count=700,
            level_total=900,
            file_total=2009,
            is_flood=True,
        ),
        0.8182,
        ["severity", "flood"],
    ),
}


@pytest.mark.parametrize("name", list(GOLDEN))
def test_policy_golden_scores(name: str) -> None:
    sig, expected_score, expected_codes = GOLDEN[name]
    result = score(sig)
    assert round(result.score, 4) == expected_score, f"{name}: score drifted"
    assert result.reason_codes == expected_codes, f"{name}: reason codes drifted"


def test_score_is_bounded() -> None:
    piled = Signals(
        level="CRITICAL",
        message="kernel panic segfault out of memory",
        template_count=1,
        level_total=1000,
        file_total=1000,
        is_flood=True,
        is_recurring=True,
        burst=True,
        is_global_rare=True,
    )
    result = score(piled)
    assert 0.0 <= result.score <= 1.0


def test_every_reason_code_is_registered() -> None:
    for _, (sig, _, _) in GOLDEN.items():
        for code in score(sig).reason_codes:
            assert code in REASON_CODES


def test_thresholds_by_sensitivity() -> None:
    assert threshold_for("low") == 0.80
    assert threshold_for("normal") == 0.70
    assert threshold_for("high") == 0.60
    assert threshold_for("unknown") == 0.70  # falls back to normal


def test_hard_flag_levels_are_desaturated() -> None:
    result = score(Signals(level="EMERGENCY", message="anything at all"))
    assert 0.85 <= result.score < 1.0
    assert "hard_flag" in result.reason_codes

    richer = score(
        Signals(
            level="EMERGENCY", message="kernel panic segfault", template_count=1, level_total=500
        )
    )
    assert result.score < richer.score < 1.0

def test_turbo_uses_the_shared_policy() -> None:
    from loglens.detection.turbo import score_templates

    merged = {
        ("CRITICAL", "conn refused"): [1, "connection refused", "CRITICAL", "db"],
        ("INFO", "ok"): [900, "request ok", "INFO", "web"],
    }
    total = 901
    templates = {t.level: t for t in score_templates(merged, total)}

    crit = templates["CRITICAL"]
    expected = score(
        Signals(
            level="CRITICAL",
            message="connection refused",
            template_count=1,
            level_total=1,
            file_total=total,
        )
    )
    assert crit.score == round(expected.score, 4)
    assert crit.reasons == expected.reason_texts
    assert crit.reasons, "turbo must now produce human-readable reasons"

    assert templates["INFO"].score < threshold_for("normal")


def test_turbo_threshold_comes_from_policy() -> None:
    from loglens.detection.turbo import score_templates

    merged = {("CRITICAL", "x"): [1, "fatal error", "CRITICAL", "svc"]}
    hi = score_templates(merged, 100, sensitivity="high")[0]
    lo = score_templates(merged, 100, sensitivity="low")[0]
    assert hi.threshold == 0.60
    assert lo.threshold == 0.80