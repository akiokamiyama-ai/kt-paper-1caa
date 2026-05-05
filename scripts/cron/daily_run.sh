#!/usr/bin/env bash
# Tribune daily auto-publish — emergency / manual fallback
#
# === Primary automation: .github/workflows/daily.yml (GitHub Actions) ===
# Day-to-day generation runs in the cloud (UTC 20:00 / JST 05:00). This
# script is kept for two scenarios only:
#   1. Manual local run (e.g. trying a fix before pushing to main)
#   2. Emergency fallback if GitHub Actions is unavailable
# It is NOT registered in cron. Run it by hand from a terminal.
#
# Generates today's archive HTML into archive/<date>.html and writes a
# per-day execution log to logs/cron_<date>.log.
#
# This script is intentionally self-contained: a non-interactive shell
# cannot rely on inheriting variables from the user's terminal session.
# The interactive guard near the top of ~/.bashrc (`*) return ;;`) means
# a naive `source ~/.bashrc` exits before reaching the export lines, so
# we surgically pull only the keys we need.
#
# Manual cron-style test (no archive overwrite, but Stage 1/2 LLM calls still
# happen so it costs ~Stage1+2 API spend; takes ~20 min):
#   env -i HOME="$HOME" PATH=/usr/bin:/bin DAILY_RUN_DRY=1 \
#       bash /home/akiok/projects/tribune/scripts/cron/daily_run.sh
#   tail -40 /home/akiok/projects/tribune/logs/cron_$(date +%Y-%m-%d).log

set -uo pipefail

PROJECT_ROOT="/home/akiok/projects/tribune"
LOG_DIR="${PROJECT_ROOT}/logs"
DATE_ISO="$(date +%Y-%m-%d)"
LOG_FILE="${LOG_DIR}/cron_${DATE_ISO}.log"
PYTHON_BIN="/usr/bin/python3"

# Surgically load the three keys regardless of the interactive guard.
if [[ -f "${HOME}/.bashrc" ]]; then
    eval "$(grep -E '^export (ANTHROPIC_API_KEY|MIIBO_API_KEY|MIIBO_AGENT_ID)=' "${HOME}/.bashrc")"
fi

mkdir -p "${LOG_DIR}"
cd "${PROJECT_ROOT}"

{
    echo "============================================================"
    echo " Tribune daily run"
    echo " Date:    ${DATE_ISO}"
    echo " Started: $(date -Iseconds)"
    echo " User:    $(whoami)"
    echo " CWD:     $(pwd)"
    echo " Python:  $(${PYTHON_BIN} --version)"
    echo " Env:     ANTHROPIC=${ANTHROPIC_API_KEY:0:10}*** (len=${#ANTHROPIC_API_KEY})"
    echo "          MIIBO=${MIIBO_API_KEY:0:10}*** (len=${#MIIBO_API_KEY})"
    echo "          MIIBO_AGENT=${MIIBO_AGENT_ID:0:10}*** (len=${#MIIBO_AGENT_ID})"
    echo "------------------------------------------------------------"

    DRY_FLAG=""
    if [[ -n "${DAILY_RUN_DRY:-}" ]]; then
        DRY_FLAG="--dry-run"
        echo " (DAILY_RUN_DRY=${DAILY_RUN_DRY} → adding --dry-run, no HTML write)"
    fi

    "${PYTHON_BIN}" -m scripts.regen_front_page_v2 --date "${DATE_ISO}" ${DRY_FLAG}
    EXIT_CODE=$?

    echo "------------------------------------------------------------"
    echo " Finished: $(date -Iseconds)"
    echo " Exit:     ${EXIT_CODE}"
    echo "============================================================"
    exit "${EXIT_CODE}"
} >> "${LOG_FILE}" 2>&1
