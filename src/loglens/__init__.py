from loglens._version import __version__

__all__ = [
    "analyze",
    "analyze_async",
    "analyze_entries",
    "AnalysisResult",
    "Anomaly",
    "LiveDetector",
    "LogLensHandler",
    "RunConfig",
    "init",
    "Monitor",
    "SlackAlerter",
    "TeamsAlerter",
    "EmailAlerter",
    "AlertDispatcher",
    "__version__",
]

_LAZY = {
    "Anomaly": ("loglens.api", "Anomaly"),
    "AnalysisResult": ("loglens.api", "AnalysisResult"),
    "analyze": ("loglens.api", "analyze"),
    "analyze_async": ("loglens.api", "analyze_async"),
    "analyze_entries": ("loglens.api", "analyze_entries"),
    "LiveDetector": ("loglens.live", "LiveDetector"),
    "LogLensHandler": ("loglens.handler", "LogLensHandler"),
    "RunConfig": ("loglens.pipeline.run", "RunConfig"),
    "init": ("loglens.monitor", "init"),
    "Monitor": ("loglens.monitor", "Monitor"),
    "SlackAlerter": ("loglens.alerts", "SlackAlerter"),
    "TeamsAlerter": ("loglens.alerts", "TeamsAlerter"),
    "EmailAlerter": ("loglens.alerts", "EmailAlerter"),
    "AlertDispatcher": ("loglens.alerts", "AlertDispatcher"),
}


def __getattr__(name):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'loglens' has no attribute {name!r}")
    import importlib

    mod = importlib.import_module(target[0])
    return getattr(mod, target[1])


def __dir__():
    return sorted(__all__)
