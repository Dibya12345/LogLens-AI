from __future__ import annotations

from loglens.domain.models import Anomaly
from loglens.infrastructure.llm import LLMConfig, run_ask, run_rca
from loglens.infrastructure.output.html_report import render_html_report


def _llm_config(provider: str = "", model: str = "", api_key: str = "", config=None):
    return config or LLMConfig.from_env(provider=provider, model=model, api_key=api_key)


def rca_for_anomalies(
    anomalies: list[Anomaly],
    *,
    source_name: str = "",
    provider: str = "",
    model: str = "",
    api_key: str = "",
    config=None,
):
    cfg = _llm_config(provider, model, api_key, config)
    return run_rca(
        [a.entry for a in anomalies if a.entry is not None],
        cfg,
        scores=[a.score for a in anomalies],
        reasons=["; ".join(a.reasons) for a in anomalies],
        source_name=source_name,
    )


def ask_about_anomalies(
    question: str,
    anomalies: list[Anomaly],
    *,
    source_name: str = "",
    provider: str = "",
    model: str = "",
    api_key: str = "",
    config=None,
):
    cfg = _llm_config(provider, model, api_key, config)
    return run_ask(
        question,
        [a.entry for a in anomalies if a.entry is not None],
        cfg,
        scores=[a.score for a in anomalies],
        reasons=["; ".join(a.reasons) for a in anomalies],
        source_name=source_name,
    )


def html_for_anomalies(
    anomalies: list[Anomaly], *, total_lines: int, source_name: str = "", rca=None
) -> str:
    levels: dict[str, int] = {}
    for a in anomalies:
        levels[a.level.upper()] = levels.get(a.level.upper(), 0) + 1
    return render_html_report(
        source=source_name or "loglens",
        total_lines=total_lines,
        anomalies=[a.entry for a in anomalies if a.entry is not None],
        level_counts=levels,
        rca_markdown=getattr(rca, "report", None) if rca is not None else None,
        rca_meta={"provider": rca.provider, "model": rca.model} if rca is not None else None,
        scores=[a.score for a in anomalies],
    )
