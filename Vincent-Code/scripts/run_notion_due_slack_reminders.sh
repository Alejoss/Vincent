#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
LOG="${ROOT}/logs/notion_due_slack_reminders.log"

{
  echo "=== $(date -Iseconds) ==="
  python scripts/notion_tasks_due_slack_reminders.py "$@"
} >>"$LOG" 2>&1

echo "Done. Log: $LOG"
