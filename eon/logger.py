"""Logging for EON — mirrors SIM patterns (console + file, journald best-effort)."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.logging import RichHandler

from eon.config import resolve_paths

LOG_FORMAT = "%(message)s"


def _try_add_journald_handler(logger: logging.Logger) -> bool:
    try:
        from systemd.journal import JournalHandler  # type: ignore[import-not-found]
    except ImportError:
        return False
    handler = JournalHandler(SYSLOG_IDENTIFIER="eon")
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logger.addHandler(handler)
    return True


def configure_logging(level: str = "INFO", log_dir: Path | None = None) -> logging.Logger:
    logger = logging.getLogger("eon")
    logger.setLevel(level)

    if not any(isinstance(h, RichHandler) for h in logger.handlers):
        console_handler = RichHandler(
            show_time=True, show_path=False, rich_tracebacks=True, markup=True
        )
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(console_handler)

    target_log_dir = log_dir or resolve_paths().log_dir
    if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        try:
            target_log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(target_log_dir / "eon.log", encoding="utf-8")
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
            )
            logger.addHandler(file_handler)
        except OSError:
            logger.warning(
                "Could not open %s for writing; continuing with console-only logging.",
                target_log_dir / "eon.log",
            )

    if not any(h.__class__.__name__ == "JournalHandler" for h in logger.handlers):
        _try_add_journald_handler(logger)

    return logger
