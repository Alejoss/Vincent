#!/usr/bin/env bash
# Classify Obsidian notes + sync to Notion (Pipeline 1, steps 2-3). Linux / GitHub Actions.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
LOG="${ROOT}/logs/productivity_classify_notion.log"

if [[ -z "${OBSIDIAN_VAULT_PATH:-}" ]]; then
  export OBSIDIAN_VAULT_PATH="$(cd "${ROOT}/.." && pwd)/Cerebro-Vincent"
fi
export SLACK_INPUT_OBSIDIAN_REL="${SLACK_INPUT_OBSIDIAN_REL:-0_Diario_Productividad/Input}"

{
  echo "=================================================="
  echo "Classify + Notion sync started: $(date -Iseconds)"
  echo "OBSIDIAN_VAULT_PATH=${OBSIDIAN_VAULT_PATH}"
  echo "LLM_PROVIDER=${LLM_PROVIDER:-auto}"
  echo "PIPELINE_RECLASSIFY=${PIPELINE_RECLASSIFY:-0}"
  echo "=================================================="
} >>"$LOG"

echo "[1/2] Classify notes..." | tee -a "$LOG"
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

echo "[2/2] Sync Obsidian -> Notion..." | tee -a "$LOG"
python scripts/sync_productivity_obsidian_to_notion.py 2>&1 | tee -a "$LOG"

echo "[OK] Classify + Notion sync completed." | tee -a "$LOG"
echo "Full log: $LOG"
