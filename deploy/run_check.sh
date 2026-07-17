#!/usr/bin/env bash
# Run one stage of the regime check, then commit + push the refreshed signal so
# GitHub Pages updates. Intended to be invoked by cron on the Oracle VM.
#
#   run_check.sh premarket   # Stage 1 (schedule ~08:50 IST)
#   run_check.sh confirm     # Stage 2 (schedule ~09:21 IST)
#
# Requires: a populated .env (UPSTOX_TOKEN valid for today), git push access.
set -euo pipefail

STAGE="${1:-premarket}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Load .env into the environment (UPSTOX_TOKEN, IFC_GIFT_NIFTY, ...).
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

PYTHON="${PYTHON:-python3}"

echo "[$(date '+%F %T %Z')] running stage: $STAGE"
if ! "$PYTHON" -m ironfly_check "$STAGE"; then
  echo "[$(date '+%F %T %Z')] stage $STAGE failed (token expired? re-run login)" >&2
  exit 1
fi

# Publish the refreshed signal to GitHub Pages.
git add site/signal.json
if git diff --cached --quiet; then
  echo "no signal change to commit"
else
  git commit -m "signal: $STAGE $(date '+%F %T %Z')" -q
  git push origin HEAD:main -q && echo "pushed"
fi
