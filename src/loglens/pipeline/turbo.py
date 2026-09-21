from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass

from loglens.pipeline.templates import template_key
from loglens.severity import TURBO_SEVERITY_DEFAULT, TURBO_SEVERITY_WEIGHT

logger = logging.getLogger("loglens.turbo")


def mask_template(msg: str) -> str:
    """Template key for turbo's dedup. Delegates to the canonical masker so the
    turbo path collapses messages the same way as the main pipeline."""
    return template_key(msg) if msg else "<empty>"


def auto_workers(
    file_size: int,
    available_mem: int | None = None,
    cpu: int | None = None,
    mem_per_worker_mb: int = 512,
    max_cap: int = 16,
    safety_frac: float = 0.6,
) -> int:
    cpu = cpu or (os.cpu_count() or 1)
    if available_mem is None:
        try:
            import psutil

            available_mem = psutil.virtual_memory().available
        except (ImportError, AttributeError, OSError):
            # psutil missing or unable to read memory — fall back to a 2 GiB assumption.
            available_mem = 2 * 1024**3
    mem_budget = int(available_mem * safety_frac)
    mem_workers = max(1, mem_budget // (mem_per_worker_mb * 1024**2))
    file_workers = max(1, file_size // (16 * 1024**2))
    return int(max(1, min(cpu, mem_workers, file_workers, max_cap)))


def split_chunks(path: str, n: int) -> list[tuple[int, int]]:
    size = os.path.getsize(path)
    if n <= 1 or size == 0:
        return [(0, size)]
    step = size // n
    bounds = [0]
    with open(path, "rb") as f:
        for i in range(1, n):
            f.seek(i * step)
            f.readline()
            bounds.append(f.tell())
    bounds.append(size)
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1) if bounds[i] < bounds[i + 1]]


def _process_range(args) -> dict[tuple[str, str], list]:
    from loglens.pipeline.parser import detect_format, parse_line

    path, start, end = args
    local: dict[tuple[str, str], list] = {}
    fmt: str | None = None
    with open(path, encoding="utf-8", errors="replace") as f:
        f.seek(start)
        pos = start
        for line in f:
            pos += len(line.encode("utf-8", "replace"))
            stripped = line.rstrip("\n")
            if stripped:
                if fmt is None:
                    fmt = detect_format(stripped)
                e = parse_line(stripped, fmt)
                if e is not None:
                    key = (e.level, mask_template(e.message))
                    slot = local.get(key)
                    if slot is None:
                        local[key] = [1, e.message, e.level, e.service]
                    else:
                        slot[0] += 1
            if pos >= end:
                break
    return local


@dataclass
class Template:
    level: str
    template: str
    count: int
    sample: str
    service: str
    score: float = 0.0

    def is_anomaly(self) -> bool:
        return self.score >= 0.5


@dataclass
class ScanResult:
    total_lines: int
    parsed_lines: int
    templates: list[Template]
    workers: int

    def redundancy(self) -> float:
        u = len(self.templates)
        return 0.0 if self.parsed_lines == 0 else 1 - u / self.parsed_lines

    def anomalies(self) -> list[Template]:
        return [t for t in self.templates if t.is_anomaly()]


def score_templates(merged: dict[tuple[str, str], list], total: int) -> list[Template]:
    if total == 0:
        return []
    unique = len(merged)
    low_redundancy = unique > 0.5 * total

    out: list[Template] = []
    for (_level, tmpl), (count, sample, lvl, svc) in merged.items():
        rarity = math.log1p(total / count) / math.log1p(total)  # 0..1
        sev = TURBO_SEVERITY_WEIGHT.get(lvl, TURBO_SEVERITY_DEFAULT)
        if low_redundancy:
            score = 0.75 * sev + 0.25 * rarity
        else:
            score = 0.55 * rarity + 0.45 * sev
        out.append(
            Template(
                level=lvl,
                template=tmpl,
                count=count,
                sample=sample,
                service=svc,
                score=round(min(score, 1.0), 4),
            )
        )
    out.sort(key=lambda t: t.score, reverse=True)
    return out


def scan_file(path: str, workers: int | None = None, **auto_kw) -> ScanResult:
    size = os.path.getsize(path)
    w = workers or auto_workers(size, **auto_kw)
    chunks = split_chunks(path, w)
    w = len(chunks)

    merged: dict[tuple[str, str], list] = {}
    if w == 1:
        merged = _process_range((path, chunks[0][0], chunks[0][1]))
    else:
        try:
            import multiprocessing as mp

            with mp.Pool(w) as pool:
                for local in pool.imap_unordered(_process_range, [(path, s, e) for s, e in chunks]):
                    for k, v in local.items():
                        slot = merged.get(k)
                        if slot is None:
                            merged[k] = v
                        else:
                            slot[0] += v[0]
        except Exception as exc:
            # Multiprocessing can fail (spawn issues, pickling, low memory).
            # Fall back to a serial scan so the run still completes.
            logger.warning(
                "parallel scan failed (%s: %s); falling back to serial",
                type(exc).__name__,
                exc,
            )
            merged = {}
            for s, e in chunks:
                for k, v in _process_range((path, s, e)).items():
                    slot = merged.get(k)
                    if slot is None:
                        merged[k] = v
                    else:
                        slot[0] += v[0]

    parsed = sum(v[0] for v in merged.values())
    templates = score_templates(merged, parsed)
    return ScanResult(total_lines=parsed, parsed_lines=parsed, templates=templates, workers=w)


def analyze(path: str, workers: int | None = None, **auto_kw) -> dict:
    res = scan_file(path, workers=workers, **auto_kw)
    anomalies = res.anomalies()
    return {
        "file": path,
        "workers": res.workers,
        "parsed_lines": res.parsed_lines,
        "unique_templates": len(res.templates),
        "redundancy": round(res.redundancy(), 4),
        "anomaly_count": len(anomalies),
        "top_anomalies": [
            {
                "score": t.score,
                "level": t.level,
                "count": t.count,
                "service": t.service,
                "sample": t.sample[:200],
            }
            for t in anomalies[:20]
        ],
    }
