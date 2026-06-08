#!/usr/bin/env bash
# Slack -> Obsidian -> classify -> Notion (Linux / GitHub Actions).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p logs
LOG="${ROOT}/logs/productivity_pipeline.log"
DAYS="${PIPELINE_DAYS:-3}"

# Monorepo: vault sibling of Vincent-Code
if [[ -z "${OBSIDIAN_VAULT_PATH:-}" ]]; then
  export OBSIDIAN_VAULT_PATH="$(cd "${ROOT}/.." && pwd)/Cerebro-Vincent"
fi
export SLACK_INPUT_OBSIDIAN_REL="${SLACK_INPUT_OBSIDIAN_REL:-0_Diario_Productividad/Input}"

{
  echo "=================================================="
  echo "Pipeline started: $(date -Iseconds)"
  echo "OBSIDIAN_VAULT_PATH=${OBSIDIAN_VAULT_PATH}"
  echo "WHISPER_PROVIDER=${WHISPER_PROVIDER:-auto}"
  echo "LLM_PROVIDER=${LLM_PROVIDER:-auto}"
  echo "=================================================="
} >>"$LOG"

echo "[1/3] Sync Slack -> Obsidian..." | tee -a "$LOG"
python scripts/sync_slack_inbox_to_obsidian.py --days "$DAYS" 2>&1 | tee -a "$LOG"

echo "[2/3] Classify notes..." | tee -a "$LOG"
classify_args=()
if [[ "${PIPELINE_RECLASSIFY:-0}" == "1" ]]; then
  classify_args+=(--reclassify)
fi
set +e
python scripts/classify_slack_input_with_ollama.py "${classify_args[@]}" 2>&1 | tee -a "$LOG"
classify_rc=${PIPESTATUS[0]}
set -e
if [[ $classify_rc -eq 2 ]]; then
  echo "[WARN] Classify had partial LLM failures (exit $classify_rc). Continuing to Notion sync." | tee -a "$LOG"
elif [[ $classify_rc -ne 0 ]]; then
  exit "$classify_rc"
fi

echo "[3/3] Sync Obsidian -> Notion..." | tee -a "$LOG"
python scripts/sync_productivity_obsidian_to_notion.py 2>&1 | tee -a "$LOG"

echo "[OK] Pipeline completed." | tee -a "$LOG"
echo "Full log: $LOG"
