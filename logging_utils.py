"""Structured logging configuration."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import config


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data
        return json.dumps(log_entry)


def setup_logging() -> None:
    """Configure structured logging to file and console with rotation."""
    root = logging.getLogger("kali_mcp")

    # Prevent duplicate handlers on re-init
    if root.handlers:
        return

    root.setLevel(logging.DEBUG if config.debug else logging.INFO)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if config.debug else logging.INFO)
    console.setFormatter(JSONFormatter())
    root.addHandler(console)

    log_file = config.log_dir / "server.log"
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10_000_000, backupCount=5  # 10MB, 5 backups
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())
    root.addHandler(file_handler)

    exec_file = config.log_dir / "executions.jsonl"
    exec_handler = RotatingFileHandler(
        exec_file, maxBytes=10_000_000, backupCount=5
    )
    exec_handler.setLevel(logging.INFO)
    exec_handler.setFormatter(JSONFormatter())
    exec_logger = logging.getLogger("kali_mcp.executions")
    exec_logger.addHandler(exec_handler)
    exec_logger.setLevel(logging.INFO)


def log_execution(result) -> None:
    """Log a completed execution to the executions log."""
    try:
        logger = logging.getLogger("kali_mcp.executions")
        logger.info(
            "tool=%s command=%s exit_code=%d success=%s duration=%.3fs timed_out=%s",
            result.tool, result.command, result.exit_code,
            result.success, result.duration, result.timed_out,
        )
    except Exception:
        pass  # Never let logging failure crash the handler
