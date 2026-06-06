#!/usr/bin/env bash
# Slack DM -> Notion task updates (Linux / GitHub Actions).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
LOG="${ROOT}/logs/slack_task_updates.log"
DAYS="${SLACK_TASK_UPDATE_DAYS:-3}"

if [[ -z "${OBSIDIAN_VAULT_PATH:-}" ]]; then
  export OBSIDIAN_VAULT_PATH="$(cd "${ROOT}/.." && pwd)/Cerebro-Vincent"
fi

{
  echo "=================================================="
  echo "Slack task updates started: $(date -Iseconds)"
  echo "OBSIDIAN_VAULT_PATH=${OBSIDIAN_VAULT_PATH}"
  echo "WHISPER_PROVIDER=${WHISPER_PROVIDER:-auto}"
  echo "LLM_PROVIDER=${LLM_PROVIDER:-auto}"
  echo "=================================================="
} >>"$LOG"

echo "[1/1] Update Notion tasks from Slack..." | tee -a "$LOG"
python scripts/update_notion_tasks_from_slack_messages.py --days "$DAYS" "$@" 2>&1 | tee -a "$LOG"

echo "[OK] Slack task updates completed." | tee -a "$LOG"
echo "Full log: $LOG"
