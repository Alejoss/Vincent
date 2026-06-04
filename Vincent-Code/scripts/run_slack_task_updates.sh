#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
LOG="${ROOT}/logs/slack_task_updates.log"
DAYS="${SLACK_TASK_UPDATE_DAYS:-3}"

{
  echo "=== $(date -Iseconds) ==="
  python scripts/update_notion_tasks_from_slack_messages.py --days "$DAYS" "$@"
} >>"$LOG" 2>&1

echo "Done. Log: $LOG"
