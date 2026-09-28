"""Structured application logging configuration."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    """Format each log record as a machine-readable JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def initialize_logging(log_directory: Path, log_level: str) -> logging.Logger:
    """Configure console and size-based rotating file logging."""
    numeric_level = logging.getLevelNamesMapping().get(log_level.upper())
    if numeric_level is None:
        raise ValueError(f"Unsupported log level: {log_level}")

    log_directory.mkdir(parents=True, exist_ok=True)
    formatter = JsonFormatter()

    file_handler = RotatingFileHandler(
        log_directory / "icu_patient_tracker.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(numeric_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    return logging.getLogger("icu_patient_tracker")


def set_log_level(log_level: str) -> None:
    """Update the configured logging threshold after settings are loaded."""
    numeric_level = logging.getLevelNamesMapping().get(log_level.upper())
    if numeric_level is None:
        raise ValueError(f"Unsupported log level: {log_level}")
    logging.getLogger().setLevel(numeric_level)
