from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LogEntry:
    timestamp: str = ""
    level: str = "INFO"
    service: str = "unknown"
    message: str = ""
    raw: str = ""
    parsed: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "service": self.service,
            "message": self.message,
            "parsed": self.parsed,
            "metadata": self.metadata,
        }
