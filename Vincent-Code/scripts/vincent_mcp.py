#!/usr/bin/env python3
"""Vincent MCP server entrypoint (stdio). Cursor launches this process."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.mcp.server import mcp  # noqa: E402


if __name__ == "__main__":
    mcp.run()
