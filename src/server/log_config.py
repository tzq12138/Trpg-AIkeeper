"""Unified logging configuration for AI-Keeper server.

Provides:
- setup_logging() — configure root logger with coloured console + optional file output
- _ColouredConsoleFormatter — ANSI-coloured single-line format

Usage:
    from .log_config import setup_logging
    setup_logging(level_name="INFO", log_file="")
"""

import logging
import sys


class _ColouredConsoleFormatter(logging.Formatter):
    """Single-line format with ANSI colour for the severity label."""

    _LEVEL_COLOUR = {
        "DEBUG":    "\033[36m",
        "INFO":     "\033[32m",
        "WARNING":  "\033[33m",
        "ERROR":    "\033[31m",
        "CRITICAL": "\033[1;31m",
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        colour = self._LEVEL_COLOUR.get(record.levelname, "")
        record.coloured_level = f"{colour}{record.levelname:<7}{self._RESET}"
        return super().format(record)


def setup_logging(level_name: str = "INFO", log_file: str = "") -> None:
    """Configure root logger with coloured console + optional file handler.

    Args:
        level_name: One of DEBUG/INFO/WARNING/ERROR/CRITICAL.
        log_file: If non-empty, also write plain-text logs to this path.
    """
    level = getattr(logging, level_name.upper(), logging.INFO)

    datefmt = "%H:%M:%S"
    console_fmt = "%(asctime)s.%(msecs)03d %(coloured_level)s %(name)-28s %(message)s"
    file_fmt    = "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)-28s %(message)s"

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # Console handler (coloured)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(_ColouredConsoleFormatter(console_fmt, datefmt))
    root.addHandler(ch)

    # Optional file handler (plain text, UTF-8, no ANSI codes)
    if log_file:
        try:
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(logging.Formatter(file_fmt, datefmt))
            root.addHandler(fh)
        except OSError as exc:
            root.warning("Cannot open log file %s: %s", log_file, exc)

    # Quiet noisy third-party libraries
    for noisy in (
        "httpx", "httpcore", "urllib3", "watchfiles",
        "uvicorn.access", "uvicorn.error", "uvicorn",
        "asyncio", "psycopg2", "psycopg2.pool",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Server packages at the configured level
    for pkg in ("src.server", "ai_keeper", "engine", "player",
                 "host", "scenario", "rules", "agent", "events"):
        logging.getLogger(pkg).setLevel(level)
