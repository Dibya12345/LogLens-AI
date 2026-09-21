from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from types import ModuleType

from loglens.pipeline.parser import detect_format, parse_line
from loglens.pipeline.run import RunConfig, run
from loglens.pipeline.turbo import scan_file

# resource is Unix-only; guarded so Windows imports still work.
resource: ModuleType | None
try:
    import resource
except ImportError:
    resource = None


@dataclass
class BenchResult:
    mode: str
    lines: int
    seconds: float
    lines_per_s: int
    time_to_first_anomaly: float | None
    anomalies: int
    peak_mb: float


def _peak_mb() -> float:
    if resource is None:
        return 0.0
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return ru / 1024 if sys.platform != "darwin" else ru / (1024 * 1024)


def bench_file(path: str, modes: list[str], workers: int = 4) -> list[BenchResult]:
    results = []

    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    fmt = detect_format(lines[0]) if lines else "generic"
    entries = [e for e in (parse_line(ln, fmt) for ln in lines) if e is not None]

    for mode in modes:
        t0 = time.perf_counter()
        ttfa = None
        if mode == "turbo":
            res = scan_file(path, workers=workers)
            n_anom = len(res.anomalies())
            n_lines = res.parsed_lines
        else:
            out = run(entries, RunConfig(mode=mode))
            flagged = list(out.flagged)
            n_anom = sum(bool(f) for f in flagged)
            n_lines = len(entries)
        dt = time.perf_counter() - t0
        if n_anom:
            ttfa = dt  # single-shot pipeline: first insight == full run time
        results.append(
            BenchResult(
                mode=mode,
                lines=n_lines,
                seconds=round(dt, 3),
                lines_per_s=int(n_lines / dt) if dt else 0,
                time_to_first_anomaly=round(ttfa, 3) if ttfa else None,
                anomalies=n_anom,
                peak_mb=round(_peak_mb(), 1),
            )
        )
    return results


def to_markdown(results: list[BenchResult], source: str) -> str:
    rows = [
        "| Mode | Lines | Time (s) | Lines/s | Anomalies | Time-to-insight (s) | Peak RAM (MB) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        rows.append(
            f"| {r.mode} | {r.lines:,} | {r.seconds} | {r.lines_per_s:,} "
            f"| {r.anomalies} | {r.time_to_first_anomaly or '—'} | {r.peak_mb} |"
        )
    return f"### LogLens Benchmark — `{source}`\n\n" + "\n".join(rows) + "\n"
