"""Shared run logging for Vincent topic / knowledge pipelines.

Creates:
  logs/{run_name}_{YYYYMMDD_HHMMSS}.log   — archive of this run
  logs/{run_name}_latest.log              — same content, overwritten each run

Also logs to stdout with timestamps.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def setup_pipeline_logging(
    run_name: str,
    *,
    verbose: bool = False,
    log_dir: Optional[Path] = None,
) -> tuple[logging.Logger, Path]:
    """
    Configure a named logger with console + timestamped file + ``_latest`` file.

    Returns ``(logger, timestamped_log_path)``.
    """
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    directory = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = (run_name or "pipeline").strip().replace(" ", "_")
    log_file = directory / f"{safe}_{stamp}.log"
    latest_file = directory / f"{safe}_latest.log"

    log = logging.getLogger(safe)
    log.handlers.clear()
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)

    fh_latest = logging.FileHandler(latest_file, mode="w", encoding="utf-8")
    fh_latest.setLevel(logging.DEBUG)
    fh_latest.setFormatter(fmt)
    log.addHandler(fh_latest)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh.setFormatter(fmt)
    log.addHandler(sh)

    log.info("Log file: %s", log_file)
    log.info("Latest log: %s", latest_file)
    return log, log_file
