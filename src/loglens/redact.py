"""Redact secrets and obvious PII from text before it leaves the machine.

LogLens runs locally, but two features send log content off-box: the LLM
root-cause analysis and alert messages. Log lines routinely contain
credentials, tokens and personal data. This module masks the high-risk,
high-confidence patterns (keys, tokens, passwords, emails, card numbers)
before that content is transmitted.

It is deliberately conservative: it targets things that are clearly secrets,
and leaves operational data like IP addresses and hostnames intact so
root-cause analysis stays useful. Redaction is best-effort defense in depth,
not a guarantee — callers should still avoid sending sensitive logs off-box.
"""

from __future__ import annotations

import re

# Each pattern maps a match to a stable placeholder. Order matters: more
# specific patterns (assignments, auth headers) run before generic ones.
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # key/secret/password/token assignments: foo_token = "abc123", api-key: xyz
    (
        re.compile(
            r"(?i)\b([a-z0-9_.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
            r"client[_-]?secret|auth|credential)[a-z0-9_.-]*)\s*[:=]\s*"
            r"(['\"]?)([^\s'\";,]{4,})\2"
        ),
        r"\1=<redacted>",
    ),
    # Authorization: Bearer <token>  /  Basic <token>
    (re.compile(r"(?i)\b(bearer|basic)\s+[a-z0-9._~+/=-]{8,}"), r"\1 <redacted>"),
    # JWTs: three base64url segments separated by dots
    (re.compile(r"\beyJ[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}\b"), "<jwt>"),
    # AWS access key IDs
    (re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA)[0-9A-Z]{16}\b"), "<aws-key>"),
    # Slack / GitHub / generic prefixed tokens (xoxb-, ghp_, sk-, etc.)
    (re.compile(r"\b(?:xox[baprs]-|ghp_|gho_|github_pat_|sk-)[A-Za-z0-9_-]{10,}\b"), "<token>"),
    # Emails
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<email>"),
    # Credit-card-like: 13-16 digits, optional separators
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "<card>"),
    # Long opaque hex/base64 blobs (>= 32 chars) — likely keys/hashes/secrets
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "<hex>"),
    (re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"), "<b64>"),
]


def redact(text: str) -> str:
    """Return ``text`` with likely secrets and PII masked. Never raises."""
    if not text:
        return text
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out
