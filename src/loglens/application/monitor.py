from __future__ import annotations

import atexit
import logging
import queue
import sys
import threading
import traceback

from loglens.detection.detector import get_severity
from loglens.domain.models import Anomaly, LogEntry
from loglens.domain.redact import redact
from loglens.infrastructure.alerts import AlertDispatcher, alerters_from_env, load_dotenv
from loglens.infrastructure.llm import LLMConfig
from loglens.infrastructure.llm.client import LLMClient
from loglens.interface.handler import LogLensHandler

logger = logging.getLogger("loglens.application.monitor")


def heuristic_rca_line(a: Anomaly) -> str:
    msg = a.message.lower()
    hints = [
        (
            ("connection refused", "connection reset", "unreachable"),
            "a dependency is down or refusing connections",
        ),
        (("timeout", "timed out"), "a dependency is responding too slowly"),
        (("out of memory", "oom", "memoryerror"), "the process ran out of memory"),
        (("disk", "no space", "i/o error"), "storage/disk trouble"),
        (("permission", "denied", "unauthorized", "forbidden"), "an auth/permission problem"),
        (("segfault", "panic", "core dump"), "the process crashed at native level"),
        (("certificate", "ssl", "tls"), "a certificate/TLS problem"),
        (("replication", "split-brain"), "database replication trouble"),
    ]
    for keys, verdict in hints:
        if any(k in msg for k in keys):
            where = a.service if a.service not in ("", "unknown") else "the app"
            return f"{verdict} (seen in {where})"
    if a.reasons:
        return a.reasons[0]
    return f"{a.level} condition in {a.service or 'the app'}"


def ai_rca_line(a: Anomaly, timeout: int = 20) -> str | None:
    try:
        cfg = LLMConfig.from_env()
        cfg.max_tokens = 60
        cfg.timeout = timeout
        client = LLMClient(cfg)
        resp = client.chat(
            [
                {
                    "role": "system",
                    "content": "You are an SRE. Reply with ONE short sentence (max "
                    "20 words) stating the most likely root cause. No "
                    "preamble, no markdown.",
                },
                {
                    "role": "user",
                    "content": f"level={a.level} service={a.service} "
                    f"message={redact(a.message)} signals={'; '.join(a.reasons)}",
                },
            ]
        )
        line = " ".join(resp.content.strip().splitlines())[:200]
        return line or None
    except Exception as exc:
        # AI enrichment is optional (no key, network down, bad response) —
        # fall back to the heuristic line. Debug-logged for diagnosis.
        logger.debug("ai_rca_line unavailable (%s: %s)", type(exc).__name__, exc)
        return None


class Monitor:
    def __init__(
        self,
        app_name: str,
        dispatcher: AlertDispatcher,
        use_ai: bool,
        capture_crashes: bool,
        min_alert_level: str,
        **detector_kwargs,
    ):
        self.app_name = app_name
        self.dispatcher = dispatcher
        self.use_ai = use_ai
        self._min_sev = _sev(min_alert_level)
        self._q: queue.Queue[Anomaly | None] = queue.Queue(maxsize=1000)
        self._worker = threading.Thread(target=self._drain, daemon=True, name="loglens-alerts")
        self._worker.start()
        self.handler = LogLensHandler(on_anomaly=self._enqueue, **detector_kwargs)
        logging.getLogger().addHandler(self.handler)
        self._stopped = False
        self._old_excepthook = None
        self._old_thread_excepthook = None
        if capture_crashes:
            self._old_excepthook = sys.excepthook
            sys.excepthook = self._excepthook
            # Also capture crashes on non-main threads (sys.excepthook misses those).
            self._old_thread_excepthook = threading.excepthook
            threading.excepthook = self._thread_excepthook
        atexit.register(self.stop)

    def _enqueue(self, a: Anomaly) -> None:
        if get_severity(a.level) > self._min_sev:
            return  # below the alerting bar
        try:
            self._q.put_nowait(a)
        except queue.Full:
            pass  # protect the app over the alert

    def _excepthook(self, exc_type, exc, tb) -> None:

        frame = traceback.extract_tb(tb)[-1] if tb else None
        where = f"{frame.filename}:{frame.lineno}" if frame else "unknown"
        a = Anomaly(
            level="FATAL",
            score=1.0,
            message=f"uncaught {exc_type.__name__}: {exc} ({where})",
            service=self.app_name,
            reasons=["uncaught exception — process crashing"],
            entry=LogEntry(level="FATAL", service=self.app_name, message=str(exc), raw=str(exc)),
        )
        # deliver synchronously — the process is about to die
        self.dispatcher.dispatch(a, self._rca_line(a))
        if self._old_excepthook:
            self._old_excepthook(exc_type, exc, tb)

    def _thread_excepthook(self, args) -> None:
        # Uncaught exception on a worker thread. Skip our own drain thread
        # (it handles its own errors) to avoid recursion.
        if args.exc_type is SystemExit or args.thread is getattr(self, "_worker", None):
            if self._old_thread_excepthook:
                self._old_thread_excepthook(args)
            return
        where = args.thread.name if args.thread else "unknown-thread"
        a = Anomaly(
            level="ERROR",
            score=0.9,
            message=f"uncaught {args.exc_type.__name__} in thread {where}: {args.exc_value}",
            service=self.app_name,
            reasons=["uncaught exception in worker thread"],
            entry=LogEntry(
                level="ERROR",
                service=self.app_name,
                message=str(args.exc_value),
                raw=str(args.exc_value),
            ),
        )
        try:
            self.dispatcher.dispatch(a, self._rca_line(a))
        except Exception as exc:
            logger.debug("thread-excepthook dispatch failed: %s", exc)
        if self._old_thread_excepthook:
            self._old_thread_excepthook(args)

    def _rca_line(self, a: Anomaly) -> str:
        if self.use_ai:
            line = ai_rca_line(a)
            if line:
                return line
        return heuristic_rca_line(a)

    def _drain(self) -> None:
        while True:
            a = self._q.get()
            if a is None:
                return
            try:
                self.dispatcher.dispatch(a, self._rca_line(a))
            except Exception as exc:
                # Alerting must never hurt the monitored app; log and move on.
                logger.debug("alert dispatch failed (%s: %s)", type(exc).__name__, exc)

    def stats(self) -> dict:
        s = self.dispatcher.stats()
        s.update(self.handler.summary())
        return s

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        try:
            logging.getLogger().removeHandler(self.handler)
        except Exception as exc:
            logger.debug("removeHandler during stop() failed: %s", exc)
        if self._old_excepthook is not None:
            sys.excepthook = self._old_excepthook
            self._old_excepthook = None
        if self._old_thread_excepthook is not None:
            threading.excepthook = self._old_thread_excepthook
            self._old_thread_excepthook = None
        try:
            self._q.put_nowait(None)
        except queue.Full:
            # Drain thread will still exit on its own timeout/shutdown.
            logger.debug("stop() could not enqueue sentinel; queue full")
        # Let the drain thread finish in-flight work instead of being killed.
        self._worker.join(timeout=2.0)


def _sev(level: str) -> int:
    return get_severity(level)


def init(
    app_name: str = "app",
    *,
    dotenv: str = ".env",
    rca: bool = True,
    capture_crashes: bool = True,
    min_alert_level: str = "ERROR",
    cooldown: float = 300.0,
    max_per_hour: int = 30,
    alerters: list | None = None,
    **detector_kwargs,
) -> Monitor:
    load_dotenv(dotenv)
    channels = alerters if alerters is not None else alerters_from_env(dotenv)
    dispatcher = AlertDispatcher(
        channels, app=app_name, cooldown=cooldown, max_per_hour=max_per_hour
    )
    return Monitor(
        app_name,
        dispatcher,
        use_ai=rca,
        capture_crashes=capture_crashes,
        min_alert_level=min_alert_level,
        **detector_kwargs,
    )
