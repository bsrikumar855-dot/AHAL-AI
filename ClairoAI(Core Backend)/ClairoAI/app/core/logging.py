"""
Structured JSON logging for ContextBridge AI.

Provides per-component loggers (api, llm, worker, db) that emit
machine-readable JSON lines. Supports correlation IDs injected
by the request middleware.
"""

import logging
import json
import sys
from datetime import datetime, timezone
from typing import Optional

from app.core.config import get_settings


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Attach correlation ID if present
        if hasattr(record, "correlation_id"):
            log_entry["correlation_id"] = record.correlation_id

        # Attach extra structured data
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data

        # Attach exception info
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def setup_logging() -> None:
    """Configure root and component loggers with JSON output."""
    settings = get_settings()
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # JSON handler for stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Quiet noisy third-party loggers
    for noisy in ("uvicorn.access", "motor", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger for a specific component.

    Usage:
        logger = get_logger("llm")
        logger.info("Model loaded", extra={"extra_data": {"model": "gemma:7b"}})
    """
    return logging.getLogger(f"contextbridge.{name}")


def log_with_context(
    logger: logging.Logger,
    level: int,
    message: str,
    correlation_id: Optional[str] = None,
    **kwargs,
) -> None:
    """Log a message with optional correlation ID and structured data."""
    extra = {}
    if correlation_id:
        extra["correlation_id"] = correlation_id
    if kwargs:
        extra["extra_data"] = kwargs
    logger.log(level, message, extra=extra)
