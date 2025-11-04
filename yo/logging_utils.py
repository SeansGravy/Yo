"""Shared logging helpers for the Yo application."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_LOGGER_ROOT = "yo"
_CONFIGURED = False


def _default_log_dir() -> Path:
    env_dir = os.environ.get("YO_LOG_DIR")
    if env_dir:
        return Path(env_dir)
    return Path("data") / "logs"


def _ensure_configured(log_dir: Optional[Path] = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    resolved_dir = log_dir or _default_log_dir()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    log_path = resolved_dir / "yo.log"

    logger = logging.getLogger(_LOGGER_ROOT)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        file_handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=5)
        file_formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter("%(message)s")
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    _CONFIGURED = True


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger configured for the Yo application."""

    _ensure_configured()
    if name is None:
        return logging.getLogger(_LOGGER_ROOT)
    full_name = f"{_LOGGER_ROOT}.{name}" if not name.startswith(f"{_LOGGER_ROOT}.") else name
    return logging.getLogger(full_name)


__all__ = ["get_logger"]
