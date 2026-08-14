"""
Structured logger — Phase 2 of the privacy architecture.

Replaces all print() calls with a structured logger that enforces log-level
privacy rules for production builds:

  INFO  — safe metadata: app names, bundle IDs, episode IDs, durations
  DEBUG — potentially sensitive: window titles (redacted in production)
  NEVER — OCR text, document content, URL paths, file contents

Production vs development is determined by the LOG_LEVEL environment variable
and the BUILDHARVEY_DEV flag. Production builds redact window titles at DEBUG
level and never log OCR text, URL paths, or document content at any level.

Usage:
    from bh_logging import get_logger
    log = get_logger(__name__)
    log.info("episode.closed", episode_id=ep.id, duration_min=ep.duration_minutes)
    log.debug("observer.window_title", app=ctx.app_name, title=ctx.window_title)
    # ^ title is automatically redacted in production

All log calls accept optional keyword arguments that are formatted as
key=value pairs after the message.
"""
import logging
import os
import sys
import time
from typing import Any

# ── Configuration ──────────────────────────────────────────────────────────────

# Production: LOG_LEVEL=INFO, BUILDHARVEY_DEV unset
# Development: LOG_LEVEL=DEBUG, BUILDHARVEY_DEV=1
_IS_DEV = os.environ.get("BUILDHARVEY_DEV", "").strip() not in ("", "0", "false", "no")
_LOG_LEVEL_STR = os.environ.get("LOG_LEVEL", "DEBUG" if _IS_DEV else "INFO").upper()
_LOG_LEVEL = getattr(logging, _LOG_LEVEL_STR, logging.INFO)

# Fields that must NEVER appear in any log output regardless of level.
# Enforced at format time by _SafeFormatter.
_NEVER_LOG_FIELDS = frozenset({
    "ocr_text", "document_content", "url_path", "file_content",
    "screenshot_b64", "raw_text", "page_text",
})

# Fields that are logged at DEBUG in dev, redacted in production.
_REDACT_IN_PRODUCTION = frozenset({
    "window_title", "title",
})


class _SafeFormatter(logging.Formatter):
    """
    Formatter that enforces privacy rules:
    - Strips _NEVER_LOG_FIELDS from the record's extra dict before formatting.
    - Redacts _REDACT_IN_PRODUCTION fields in production builds.
    """

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        # Collect structured key=value pairs from the record's __dict__
        extras = {}
        for key, val in record.__dict__.items():
            if key.startswith("_") or key in _STANDARD_ATTRS:
                continue
            if key in _NEVER_LOG_FIELDS:
                continue  # silently drop — must never appear in logs
            if key in _REDACT_IN_PRODUCTION and not _IS_DEV:
                extras[key] = "[redacted]"
            else:
                extras[key] = val

        base = super().format(record)
        if extras:
            kv = " ".join(f"{k}={repr(v)}" for k, v in extras.items())
            return f"{base} | {kv}"
        return base


# Attributes that are always on a LogRecord (not caller extras)
_STANDARD_ATTRS = frozenset({
    "name", "msg", "args", "created", "filename", "funcName", "levelname",
    "levelno", "lineno", "module", "msecs", "pathname", "process",
    "processName", "relativeCreated", "thread", "threadName", "exc_info",
    "exc_text", "stack_info", "message", "asctime",
})


def _build_handler() -> logging.Handler:
    handler = logging.StreamHandler(sys.stderr)
    fmt = _SafeFormatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(fmt)
    return handler


# Root logger for BuildHarvey — all module loggers inherit from this.
_root = logging.getLogger("buildharvey")
if not _root.handlers:
    _root.addHandler(_build_handler())
_root.setLevel(_LOG_LEVEL)
_root.propagate = False


class BHLogger:
    """
    Thin wrapper around stdlib Logger that provides structured key=value logging
    with compile-time privacy enforcement.
    """

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(f"buildharvey.{name}")

    def info(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.INFO, msg, **kwargs)

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, msg, **kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, **kwargs)

    def _log(self, level: int, msg: str, **kwargs: Any) -> None:
        if not self._logger.isEnabledFor(level):
            return
        # Filter never-log fields before they reach the formatter
        safe_kwargs = {
            k: v for k, v in kwargs.items()
            if k not in _NEVER_LOG_FIELDS
        }
        self._logger.log(level, msg, extra=safe_kwargs)


def get_logger(name: str) -> BHLogger:
    """Return a BHLogger for the given module name."""
    return BHLogger(name)
