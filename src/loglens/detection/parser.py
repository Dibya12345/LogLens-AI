from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Iterator

from loglens.detection.cloud import map_cloud_json
from loglens.domain.models import LogEntry

logger = logging.getLogger("loglens.parser")

# JSON is detected/parsed separately (see detect_format/parse_line), so it is
# intentionally not in this regex table — keeping every value a real Pattern.
PATTERNS: dict[str, re.Pattern[str]] = {
    "NGINX": re.compile(
        r'(?P<ip>\S+) - - \[(?P<time>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+)[^"]*" (?P<status>\d+) (?P<bytes>\d+)'
    ),
    "APACHE": re.compile(
        r'(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+)[^"]*" (?P<status>\d+) (?P<bytes>\d+)'
    ),
    "APP_LOG": re.compile(
        r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,\.]\d+)\s+"
        r"(?P<level>[A-Z]+)\s+\[(?P<thread>[^\]]*)\]\s+"
        r"(?P<service>[^:\s]+):\s*(?P<message>.*)"
    ),
    "ZK_LOG": re.compile(
        r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,\.]\d+)\s+-\s+"
        r"(?P<level>[A-Z]+)\s+\[(?P<thread>.+)\]\s+-\s+(?P<message>.+)"
    ),
    "SPARK_LOG": re.compile(
        r"^(?P<time>\d\d/\d\d/\d\d \d\d:\d\d:\d\d)\s+"
        r"(?P<level>[A-Z]+)\s+(?P<service>[^:]+):\s*(?P<message>.*)"
    ),
    "APACHE_ERR": re.compile(
        r"^\[(?P<time>\w{3} \w{3} \d+ [\d:]+ \d{4})\]\s+"
        r"\[(?P<level>\w+)\]\s+(?P<message>.+)"
    ),
    "WINCBS": re.compile(
        r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\s+"
        r"(?P<level>\w+)\s+(?P<service>\w+)\s+(?P<message>.+)"
    ),
    "HDFS": re.compile(
        r"^(?P<date>\d{6})\s+(?P<time>\d{6})\s+(?P<pid>\d+)\s+"
        r"(?P<level>[A-Z]+)\s+(?P<service>\S+?):\s+(?P<message>.+)"
    ),
    "HPC": re.compile(
        r"^(?P<label>-|[A-Z0-9_]+)\s+(?P<epoch>\d{9,10})\s+"
        r"(?P<date>\d{4}\.\d\d\.\d\d)\s+(?P<node>\S+)\s+(?P<message>.+)"
    ),
    "HEALTHAPP": re.compile(
        r"^(?P<time>\d{8}-\d{1,2}:\d{1,2}:\d{1,2}:\d+)\|"
        r"(?P<service>[^|]+)\|(?P<pid>[^|]+)\|(?P<message>.+)"
    ),
    "PROXIFIER": re.compile(
        r"^\[(?P<time>[\d.]+ [\d:]+)\]\s+"
        r"(?P<service>\S+?\.exe(?:\s+\*\d+)?)\s+-\s+(?P<message>.+)"
    ),
    "SYSLOG": re.compile(
        r"(?P<time>\w+\s+\d+\s+[\d:]+) (?P<host>\S+) (?P<service>\S+?):? (?P<message>.+)"
    ),
    "STANDARD": re.compile(
        r"(?P<time>\d{4}-\d{2}-\d{2}T[\d:]+Z)\s+(?P<level>\w+)\s+\[(?P<service>[^\]]+)\]\s+(?P<message>.+)"
    ),
    "LOGLENS": re.compile(
        r"(?P<time>\d{4}-\d{2}-\d{2}T[\d:]+Z)\s+(?P<level>\w+)\s+(?P<service>\S+)\s+(?P<message>.+)"
    ),
}


_PRI_RE = re.compile(r"^<(\d{1,3})>\s*")
_FACILITY_SEV_RE = re.compile(
    r"\b(?:kern|user|mail|daemon|auth(?:priv)?|syslog|lpr|news|uucp|cron|ftp"
    r"|local[0-7])\.(emerg|alert|crit|err|error|warning|warn|notice|info"
    r"|debug)\b",
    re.IGNORECASE,
)
SYSLOG_SEVERITY = {
    0: "EMERGENCY",
    1: "ALERT",
    2: "CRITICAL",
    3: "ERROR",
    4: "WARN",
    5: "NOTICE",
    6: "INFO",
    7: "DEBUG",
}
_TEXT_SEVERITY = {
    "emerg": "EMERGENCY",
    "alert": "ALERT",
    "crit": "CRITICAL",
    "err": "ERROR",
    "error": "ERROR",
    "warning": "WARN",
    "warn": "WARN",
    "notice": "NOTICE",
    "info": "INFO",
    "debug": "DEBUG",
}


def _syslog_level(line: str) -> str:
    m = _PRI_RE.match(line)
    if m:
        return SYSLOG_SEVERITY[int(m.group(1)) % 8]
    m = _FACILITY_SEV_RE.search(line)
    if m:
        return _TEXT_SEVERITY[m.group(1).lower()]
    return "INFO"


_PLAINTEXT_LEVEL_RE = re.compile(
    r"\b(EMERG(?:ENCY)?|ALERT|CRIT(?:ICAL)?|FATAL|SEVERE|ERROR|ERR|EXCEPTION"
    r"|WARN(?:ING)?|FAIL(?:ED|URE)?|NOTICE|DEBUG|TRACE|INFO)\b",
    re.IGNORECASE,
)
_PLAINTEXT_LEVEL_MAP = {
    "emerg": "EMERGENCY",
    "emergency": "EMERGENCY",
    "alert": "ALERT",
    "crit": "CRITICAL",
    "critical": "CRITICAL",
    "fatal": "CRITICAL",
    "severe": "CRITICAL",
    "error": "ERROR",
    "err": "ERROR",
    "exception": "ERROR",
    "fail": "ERROR",
    "failed": "ERROR",
    "failure": "ERROR",
    "warn": "WARN",
    "warning": "WARN",
    "notice": "NOTICE",
    "debug": "DEBUG",
    "trace": "DEBUG",
    "info": "INFO",
}


def infer_level(text: str) -> str:
    m = _PLAINTEXT_LEVEL_RE.search(text)
    if m:
        return _PLAINTEXT_LEVEL_MAP.get(m.group(1).lower(), "INFO")
    return "INFO"


def _norm_level(tok: str) -> str:
    return _PLAINTEXT_LEVEL_MAP.get(tok.lower(), tok.upper())


def status_to_level(status: int) -> str:
    if status in (503, 504):
        return "CRITICAL"
    if status >= 500:
        return "ERROR"
    if status == 404:
        return "INFO"
    if status >= 400:
        return "WARN"
    return "INFO"


def detect_format(line: str) -> str:
    line = line.strip()
    if not line:
        return "UNKNOWN"
    probe = _PRI_RE.sub("", line)
    if probe.startswith(("{", "[")):
        try:
            json.loads(probe)
            return "JSON"
        except ValueError:
            pass
    for fmt, pattern in PATTERNS.items():
        if fmt == "JSON":
            continue
        if pattern and pattern.match(probe):
            return fmt
    return "PLAINTEXT"


def parse_line(line: str, fmt: str) -> LogEntry | None:
    line = line.strip()
    if not line:
        return None
    try:
        if fmt == "JSON":
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError("not an object")
            cloud = map_cloud_json(data, line)
            if cloud is not None:
                return cloud
            return LogEntry(
                timestamp=str(data.get("timestamp", data.get("time", ""))),
                level=str(data.get("level", data.get("severity", "INFO"))).upper(),
                service=str(data.get("service", data.get("logger", "unknown"))),
                message=str(data.get("message", data.get("msg", line))),
                raw=line,
                metadata={
                    k: v
                    for k, v in data.items()
                    if k
                    not in (
                        "timestamp",
                        "time",
                        "level",
                        "severity",
                        "service",
                        "logger",
                        "message",
                        "msg",
                    )
                },
            )
        if fmt == "STANDARD":
            m = PATTERNS["STANDARD"].match(line)
            if m:
                return LogEntry(
                    timestamp=m.group("time"),
                    level=m.group("level").upper(),
                    service=m.group("service"),
                    message=m.group("message").strip(),
                    raw=line,
                )
        if fmt in ("NGINX", "APACHE"):
            m = PATTERNS[fmt].match(line)
            if m:
                status = int(m.group("status"))
                return LogEntry(
                    timestamp=m.group("time"),
                    level=status_to_level(status),
                    service=fmt.lower(),
                    message=f"{m.group('method')} {m.group('path')} {status}",
                    raw=line,
                    metadata={"ip": m.group("ip"), "status": m.group("status")},
                )
        if fmt == "HDFS":
            m = PATTERNS["HDFS"].match(line)
            if m:
                return LogEntry(
                    timestamp=f"{m.group('date')} {m.group('time')}",
                    level=_norm_level(m.group("level")),  # FATAL->CRITICAL
                    service=m.group("service").rstrip(":"),
                    message=m.group("message").strip(),
                    raw=line,
                    metadata={"pid": m.group("pid")},
                )
        if fmt == "SYSLOG":
            stripped = _PRI_RE.sub("", line)
            m = PATTERNS["SYSLOG"].match(stripped)
            if m:
                msg = m.group("message").strip()
                lvl = _syslog_level(line)
                if lvl == "INFO":
                    lvl = infer_level(msg)
                return LogEntry(
                    timestamp=m.group("time"),
                    level=lvl,
                    service=m.group("service").rstrip(":"),
                    message=msg,
                    raw=line,
                )
        if fmt == "LOGLENS":
            m = PATTERNS["LOGLENS"].match(line)
            if m:
                return LogEntry(
                    timestamp=m.group("time"),
                    level=m.group("level").upper(),
                    service=m.group("service").strip("[]"),
                    message=m.group("message").strip(),
                    raw=line,
                )
        if fmt in ("APP_LOG", "ZK_LOG", "SPARK_LOG"):
            m = PATTERNS[fmt].match(line)
            if m:
                gd = m.groupdict()
                svc = (gd.get("service") or "").strip() or "zookeeper"
                return LogEntry(
                    timestamp=m.group("time"),
                    level=_norm_level(m.group("level")),
                    service=svc,
                    message=m.group("message").strip(),
                    raw=line,
                    metadata={"thread": gd.get("thread", "")},
                )
        if fmt == "APACHE_ERR":
            m = PATTERNS["APACHE_ERR"].match(line)
            if m:
                return LogEntry(
                    timestamp=m.group("time"),
                    level=_norm_level(m.group("level")),
                    service="apache",
                    message=m.group("message").strip(),
                    raw=line,
                )
        if fmt == "WINCBS":
            m = PATTERNS["WINCBS"].match(line)
            if m:
                return LogEntry(
                    timestamp=m.group("time"),
                    level=_norm_level(m.group("level")),
                    service=m.group("service"),
                    message=m.group("message").strip(),
                    raw=line,
                )
        if fmt == "HPC":
            m = PATTERNS["HPC"].match(line)
            if m:
                msg = m.group("message").strip()
                return LogEntry(
                    timestamp=m.group("date"),
                    level=infer_level(msg),
                    service=m.group("node"),
                    message=msg,
                    raw=line,
                    metadata={"alert_label": m.group("label")},
                )
        if fmt == "HEALTHAPP":
            m = PATTERNS["HEALTHAPP"].match(line)
            if m:
                return LogEntry(
                    timestamp=m.group("time"),
                    level=infer_level(m.group("message")),
                    service=m.group("service").strip(),
                    message=m.group("message").strip(),
                    raw=line,
                )
        if fmt == "PROXIFIER":
            m = PATTERNS["PROXIFIER"].match(line)
            if m:
                return LogEntry(
                    timestamp=m.group("time"),
                    level=infer_level(m.group("message")),
                    service=m.group("service").strip(),
                    message=m.group("message").strip(),
                    raw=line,
                )
        return LogEntry(
            timestamp="",
            level=infer_level(line),
            service="unknown",
            message=line,
            raw=line,
            parsed=False,
        )
    except Exception as exc:
        # Never let one malformed line abort a whole file — degrade to an
        # unparsed entry. Logged at debug since noisy logs are the norm.
        logger.debug("parse fell back to raw (%s: %s)", type(exc).__name__, exc)
        return LogEntry(
            timestamp="",
            level="INFO",
            service="unknown",
            message=line,
            raw=line,
            parsed=False,
        )


_CONTINUATION_RE = re.compile(
    r"^[ \t]+\S"
    r"|^(?:at\s+\S"
    r"|Caused by:"
    r"|\.\.\.\s*\d+\s+more"
    r"|Traceback \(most recent call last\)"
    r"|File \")"
)

_MAX_CONTINUATION = 200


class StreamParser:
    def __init__(self, fmt: str | None = None):
        self.forced_fmt = fmt
        self.sticky: str | None = fmt
        self.first_format: str | None = None
        self._pending: LogEntry | None = None
        self._pending_continuations = 0
        self.stats = {
            "lines": 0,
            "blank": 0,
            "continuations": 0,
            "fallback": 0,
            "format_switches": 0,
        }

    def _sticky_matches(self, line: str) -> bool:
        fmt = self.sticky
        if fmt is None:
            return False
        if fmt == "JSON":
            return line.lstrip().startswith("{")
        if fmt in ("PLAINTEXT", "UNKNOWN"):
            return False
        pattern = PATTERNS.get(fmt)
        return bool(pattern and pattern.match(_PRI_RE.sub("", line)))

    def _format_for(self, line: str) -> str:
        if self.forced_fmt:
            return self.forced_fmt
        if self._sticky_matches(line):
            assert self.sticky is not None  # _sticky_matches is False when sticky is None
            return self.sticky
        detected = detect_format(line)
        if detected in ("PLAINTEXT", "UNKNOWN"):
            return self.sticky or detected
        if self.sticky is not None and detected != self.sticky:
            self.stats["format_switches"] += 1
        self.sticky = detected
        return detected

    def feed(self, line: str) -> LogEntry | None:
        self.stats["lines"] += 1
        if not line.strip():
            self.stats["blank"] += 1
            return None

        if (
            self._pending is not None
            and self._pending_continuations < _MAX_CONTINUATION
            and _CONTINUATION_RE.match(line)
        ):
            self._pending.message += " | " + line.strip()
            self._pending.raw += "\n" + line.rstrip("\n")
            self._pending_continuations += 1
            self.stats["continuations"] += 1
            return None

        fmt = self._format_for(line)
        if self.first_format is None:
            self.first_format = fmt
        entry = parse_line(line, fmt)
        if entry is not None and not entry.parsed:
            self.stats["fallback"] += 1

        completed, self._pending = self._pending, entry
        self._pending_continuations = 0
        return completed

    def flush(self) -> LogEntry | None:
        completed, self._pending = self._pending, None
        return completed

    def parse_all(self, lines: Iterable[str]) -> Iterator[LogEntry]:
        for line in lines:
            entry = self.feed(line)
            if entry is not None:
                yield entry
        entry = self.flush()
        if entry is not None:
            yield entry
