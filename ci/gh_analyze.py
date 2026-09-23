#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

_MODE_FLAG = {"fast": [], "turbo": ["--turbo"], "deep": ["--deep"]}
_ANNOTATION = {
    "EMERGENCY": "error",
    "ALERT": "error",
    "FATAL": "error",
    "CRITICAL": "error",
    "ERROR": "error",
    "WARNING": "warning",
    "WARN": "warning",
}


def _run_loglens(source: str, mode: str, fail_on: str) -> tuple[dict, int]:
    """Invoke the CLI and return (parsed_json, exit_code)."""
    cmd = ["loglens", "analyze", "--source", source, "--format", "json"]
    cmd += _MODE_FLAG.get(mode, [])
    if fail_on:
        cmd += ["--fail-on", fail_on]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.stderr.write("LogLens: could not parse analyzer output.\n")
        sys.stderr.write(proc.stdout[:2000])
        sys.stderr.write(proc.stderr[:2000])
        raise SystemExit(1) from None
    return data, proc.returncode


def _emoji(level: str) -> str:
    lvl = level.upper()
    if lvl in ("EMERGENCY", "ALERT", "FATAL", "CRITICAL"):
        return "🔴"
    if lvl in ("ERROR",):
        return "🟠"
    if lvl in ("WARNING", "WARN"):
        return "🟡"
    return "⚪"


def _write_summary(data: dict, limit: int = 25) -> str:
    """Build the Markdown job summary and return it."""
    anomalies = data.get("anomalies", [])
    n = data.get("anomaly_count", len(anomalies))
    mode = data.get("mode", "fast")
    parsed = data.get("lines_parsed", 0)
    incident = data.get("incident", False)

    lines = [
        "## 🔍 LogLens AI — log analysis",
        "",
        f"**{n} anomaly{'ies' if n != 1 else ''}** in **{parsed:,}** parsed lines "
        f"· mode `{mode}`" + ("  ·  🚨 **INCIDENT**" if incident else ""),
        "",
    ]
    if not anomalies:
        lines.append("✅ No anomalies detected.")
        return "\n".join(lines) + "\n"

    lines += [
        "| | Level | Service | ×N | Score | Message | Why |",
        "|--|--|--|--|--|--|--|",
    ]
    for a in anomalies[:limit]:
        msg = str(a.get("message", "")).replace("|", "\\|")[:80]
        why = "; ".join(a.get("reasons", []) or []).replace("|", "\\|")[:90]
        lines.append(
            f"| {_emoji(a.get('level', ''))} | {a.get('level', '')} | "
            f"{a.get('service', '')} | {a.get('count', 1):,} | "
            f"{a.get('score', 0):.2f} | {msg} | {why} |"
        )
    if n > limit:
        lines.append("")
        lines.append(f"_…and {n - limit} more._")
    return "\n".join(lines) + "\n"


def _emit_annotations(data: dict, limit: int = 20) -> None:
    """Emit GitHub inline annotations for the top anomalies."""
    for a in data.get("anomalies", [])[:limit]:
        level = _ANNOTATION.get(str(a.get("level", "")).upper())
        if not level:
            continue
        title = f"LogLens: {a.get('level')} in {a.get('service', 'log')}"
        msg = str(a.get("message", ""))[:180]
        why = "; ".join(a.get("reasons", []) or [])
        body = f"{msg}  —  {why}" if why else msg
        # Annotations without a file attach to the run; safe and always valid.
        print(f"::{level} title={title}::{body}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--mode", default="fast")
    ap.add_argument("--fail-on", default="")
    args = ap.parse_args()

    data, code = _run_loglens(args.source, args.mode, args.fail_on)

    summary = _write_summary(data)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(summary)
    else:  # local run — print it so the script is testable outside CI
        print(summary)

    _emit_annotations(data)

    n = data.get("anomaly_count", 0)
    print(f"LogLens: {n} anomaly(ies) found (mode={data.get('mode')}).")
    return code  # propagate --fail-on gating (2 == build should fail)


if __name__ == "__main__":
    raise SystemExit(main())
