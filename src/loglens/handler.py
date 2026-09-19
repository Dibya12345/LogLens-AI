from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone

from loglens.live import LiveDetector
from loglens.models import Anomaly, LogEntry
from loglens.severity import canonical_level

logger = logging.getLogger("loglens.handler")


class LogLensHandler(logging.Handler):
    def __init__(
        self,
        on_anomaly: Callable[[Anomaly], None] | None = None,
        *,
        level: int = logging.NOTSET,
        detector: LiveDetector | None = None,
        **detector_kwargs,
    ):
        super().__init__(level)
        self.on_anomaly = on_anomaly
        self.detector = detector or LiveDetector(**detector_kwargs)
        self._max_anomalies = 5000
        self.anomalies: list[Anomaly] = []
        self._lock = threading.Lock()  # detector isn't thread-safe
        self._reentry = threading.local()

    def _to_entry(self, record: logging.LogRecord) -> LogEntry:
        lvl = canonical_level(record.levelname)
        try:
            msg = record.getMessage()
        except Exception:
            # Bad %-format args in the log call; degrade to the raw template.
            logger.debug("record.getMessage() failed for %r", record.msg, exc_info=True)
            msg = str(record.msg)
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        return LogEntry(
            timestamp=ts,
            level=lvl,
            service=record.name or "unknown",
            message=msg,
            raw=msg,
            metadata={"logger": record.name, "pid": record.process},
        )

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(self._reentry, "active", False):
            return
        self._reentry.active = True
        try:
            with self._lock:
                hits = self.detector.feed_entry(self._to_entry(record))
            for a in hits:
                self._dispatch(a, record)
        except Exception:
            self.handleError(record)
        finally:
            self._reentry.active = False

    def _dispatch(self, anomaly: Anomaly, record: logging.LogRecord | None) -> None:
        self.anomalies.append(anomaly)
        if len(self.anomalies) > self._max_anomalies:
            del self.anomalies[: -self._max_anomalies]
        if self.on_anomaly is not None:
            try:
                self.on_anomaly(anomaly)
            except Exception:
                if record is not None:
                    self.handleError(record)
                else:
                    # Flush path has no record to route through handleError.
                    logger.debug("on_anomaly callback failed during flush", exc_info=True)

    def flush(self) -> None:
        if getattr(self._reentry, "active", False):
            return
        self._reentry.active = True
        try:
            with self._lock:
                hits = self.detector.flush()
            for a in hits:
                self._dispatch(a, None)
        finally:
            self._reentry.active = False

    def summary(self) -> dict:
        return self.detector.summary()

    def close(self) -> None:
        try:
            self.flush()
        finally:
            super().close()
