from __future__ import annotations

from loglens.domain.models import LogEntry

GCP_SEVERITY = {
    "DEFAULT": "INFO",
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "NOTICE": "NOTICE",
    "WARNING": "WARN",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
    "ALERT": "ALERT",
    "EMERGENCY": "EMERGENCY",
}
AZURE_LEVEL = {
    "informational": "INFO",
    "information": "INFO",
    "verbose": "DEBUG",
    "warning": "WARN",
    "error": "ERROR",
    "critical": "CRITICAL",
}


def _dig(d: dict, path: str, default=""):
    cur = d
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def detect_cloud_provider(d: dict) -> str | None:
    if "eventSource" in d or ("eventName" in d and "awsRegion" in d):
        return "AWS"
    if (
        "logName" in d
        or "protoPayload" in d
        or "jsonPayload" in d
        or (isinstance(d.get("resource"), dict) and "severity" in d)
    ):
        return "GCP"
    if "resourceId" in d and ("operationName" in d or "category" in d):
        return "AZURE"
    if "time" in d and "operationName" in d:
        return "AZURE"
    return None


def map_cloud_json(d: dict, line: str) -> LogEntry | None:
    provider = detect_cloud_provider(d)
    if provider is None:
        return None

    if provider == "AWS":
        err_code = d.get("errorCode")
        err_msg = d.get("errorMessage")
        level = "ERROR" if (err_code or err_msg) else "INFO"
        service = str(d.get("eventSource", "aws")).split(".")[0]
        message = str(d.get("eventName", ""))
        if err_code or err_msg:
            message = f"{message} [{err_code or ''}] {err_msg or ''}".strip()
        return LogEntry(
            timestamp=str(d.get("eventTime", "")),
            level=level,
            service=service or "aws",
            message=message.strip(),
            raw=line,
            metadata={
                "provider": "AWS",
                "region": d.get("awsRegion"),
                "source_ip": d.get("sourceIPAddress"),
                "event_source": d.get("eventSource"),
                "user": _dig(d, "userIdentity.arn", None),
            },
        )

    if provider == "GCP":
        sev = str(d.get("severity", "DEFAULT")).upper()
        level = GCP_SEVERITY.get(sev, "INFO")
        service = _dig(d, "resource.type", "gcp") or "gcp"
        payload = d.get("jsonPayload") or d.get("protoPayload") or {}
        message = (
            d.get("textPayload")
            or (payload.get("message") if isinstance(payload, dict) else "")
            or (payload.get("methodName") if isinstance(payload, dict) else "")
            or d.get("logName", "")
        )
        return LogEntry(
            timestamp=str(d.get("timestamp", "")),
            level=level,
            service=str(service),
            message=str(message).strip(),
            raw=line,
            metadata={
                "provider": "GCP",
                "log_name": d.get("logName"),
                "project": _dig(d, "resource.labels.project_id", None),
            },
        )

    if provider == "AZURE":
        lvl = str(d.get("level", "")).lower()
        level = AZURE_LEVEL.get(lvl, "INFO")
        service = d.get("category") or d.get("resourceId") or "azure"
        message = d.get("operationName") or _dig(d, "properties.statusMessage", "") or ""
        return LogEntry(
            timestamp=str(d.get("time", "")),
            level=level,
            service=str(service),
            message=str(message).strip(),
            raw=line,
            metadata={
                "provider": "AZURE",
                "resource_id": d.get("resourceId"),
                "status": d.get("resultType") or _dig(d, "properties.status", None),
            },
        )
    return None
