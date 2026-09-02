"""Vincent-Code roots and env loading for the MCP server."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
LOG_DIR = PROJECT_ROOT / "logs"
CACHE_DIR = PROJECT_ROOT / "cache"
JOBS_DIR = CACHE_DIR / "mcp"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)


def python_executable() -> str:
    win = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
    nix = PROJECT_ROOT / "venv" / "bin" / "python"
    if win.is_file():
        return str(win)
    if nix.is_file():
        return str(nix)
    return sys.executable


def env_present(name: str) -> bool:
    return bool((os.getenv(name) or "").strip())


def path_exists(rel_or_abs: str | Path) -> bool:
    return Path(rel_or_abs).is_file() or Path(rel_or_abs).is_dir()
