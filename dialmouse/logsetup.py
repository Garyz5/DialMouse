"""Logging / debug-output setup for DialMouse.

Design goals tied to the build requirements:

  * Comprehensive, structured debug output so we can refine as we build.
  * No unbounded growth: the file handler rotates (bounded disk usage), so a
    long-running session can never fill the USB drive or leak memory through
    an ever-growing log buffer.
  * Quiet by default, loud with --verbose. The file always captures DEBUG so a
    post-mortem is possible even when the console was at INFO.

Nothing here opens a network socket or touches another system; it only writes
to stderr and (optionally) a local rotating file.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

LOGGER_NAME = "dialmouse"

# A console format that is readable at a glance but still carries the module and
# level so debug traces are useful. The file format additionally carries the
# logger name and is identical otherwise.
_CONSOLE_FMT = "%(asctime)s  %(levelname)-7s  %(name)s.%(module)s: %(message)s"
_DATE_FMT = "%H:%M:%S"

# Bounded log file: 1 MiB per file, 3 rotations kept => at most ~4 MiB on disk.
_LOG_MAX_BYTES = 1 * 1024 * 1024
_LOG_BACKUPS = 3


def setup_logging(verbose: bool = False, log_dir: Optional[Path] = None) -> logging.Logger:
    """Configure and return the shared ``dialmouse`` logger.

    Args:
        verbose: If True the console shows DEBUG; otherwise INFO.
        log_dir: Optional directory for a rotating debug log. If None, no file
            is written (console only). If given, the directory is created.

    Returns:
        The configured logger. Safe to call more than once; handlers are reset
        each time so we never accumulate duplicate handlers (a classic leak).
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)  # capture everything; handlers filter below.

    # Reset handlers so repeated setup_logging() calls don't stack up.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter(_CONSOLE_FMT, datefmt=_DATE_FMT))
    logger.addHandler(console)

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "dialmouse.log"
            file_handler = logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=_LOG_MAX_BYTES,
                backupCount=_LOG_BACKUPS,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)  # full detail always goes to file.
            file_handler.setFormatter(logging.Formatter(_CONSOLE_FMT, datefmt=_DATE_FMT))
            logger.addHandler(file_handler)
            logger.debug("Debug log file: %s (rotating, max ~%d MiB)",
                         log_path, (_LOG_MAX_BYTES * (_LOG_BACKUPS + 1)) // (1024 * 1024))
        except OSError as exc:
            # A read-only USB path or permission issue must never crash the app;
            # fall back to console-only and say so.
            logger.warning("Could not open log file in %s (%s); console-only logging.",
                           log_dir, exc)

    # Do not propagate to the root logger (avoids duplicate lines if a host app
    # has already configured logging).
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    """Return the shared logger (already configured by setup_logging)."""
    return logging.getLogger(LOGGER_NAME)
