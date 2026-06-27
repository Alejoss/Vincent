#!/usr/bin/env bash
# Slack DM -> Obsidian only (Pipeline 1, step 1). Linux / GitHub Actions.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
LOG="${ROOT}/logs/slack_inbox_sync.log"
DAYS="${SLACK_INBOX_DAYS:-${PIPELINE_DAYS:-3}}"

if [[ -z "${OBSIDIAN_VAULT_PATH:-}" ]]; then
  export OBSIDIAN_VAULT_PATH="$(cd "${ROOT}/.." && pwd)/Cerebro-Vincent"
fi
export SLACK_INPUT_OBSIDIAN_REL="${SLACK_INPUT_OBSIDIAN_REL:-0_Diario_Productividad/Input}"

{
  echo "=================================================="
  echo "Slack inbox sync started: $(date -Iseconds)"
  echo "OBSIDIAN_VAULT_PATH=${OBSIDIAN_VAULT_PATH}"
  echo "WHISPER_PROVIDER=${WHISPER_PROVIDER:-auto}"
  echo "=================================================="
} >>"$LOG"

echo "[1/1] Sync Slack -> Obsidian..." | tee -a "$LOG"
python scripts/sync_slack_inbox_to_obsidian.py --days "$DAYS" 2>&1 | tee -a "$LOG"

echo "[OK] Slack inbox sync completed." | tee -a "$LOG"
echo "Full log: $LOG"
