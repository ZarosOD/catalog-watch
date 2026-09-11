#!/usr/bin/env bash
# What the scheduler actually calls. Both the cron line and the systemd unit
# point here, so there is one place that knows how to run a scheduled scrape.
#
# Written for cron's environment, which is not your shell's: no PATH beyond
# /usr/bin:/bin, no virtualenv, no cwd, and stdout going to mail rather than a
# terminal. `make schedule-check` runs this file with `env -i` to prove it.
#
#   schedule/run.sh [extra watch.py arguments...]
#
# Exit codes are watch.py's, so a scheduler can act on them:
#   0  ran, nothing flagged
#   1  something needs review   (with --fail-on-review)
#   2  something changed        (with --fail-on-change)
#   3  usage or config problem
#   4  the site could not be fetched

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Where to look, and where the previous run lives. Override in the crontab or
# the systemd unit rather than editing this file.
TARGET="${CATALOG_WATCH_TARGET:---serve fixtures/site-day2}"
STATE="${CATALOG_WATCH_STATE:-$REPO_ROOT/state/catalog.json}"
OUT="${CATALOG_WATCH_OUT:-$REPO_ROOT/out}"
SITE="${CATALOG_WATCH_SITE:-$REPO_ROOT/sites/fixture.json}"
LOG_DIR="${CATALOG_WATCH_LOG_DIR:-$REPO_ROOT/logs}"

mkdir -p "$LOG_DIR" "$OUT"
LOG="$LOG_DIR/catalog-watch.log"

PY="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  # A scheduled job that dies because nobody activated a venv is the classic
  # way this breaks. Build it here, the same way make does.
  echo "$(date -u +%FT%TZ) no .venv; bootstrapping" >>"$LOG"
  "$REPO_ROOT/demo/setup.sh" >>"$LOG" 2>&1
fi

STAMP="$(date -u +%FT%TZ)"
echo "$STAMP start" >>"$LOG"

set +e
# TARGET is unquoted on purpose: it carries two words in the --serve case.
# shellcheck disable=SC2086
"$PY" watch.py $TARGET \
  --site "$SITE" \
  --state "$STATE" \
  --out "$OUT" \
  --report \
  --quiet \
  "$@" >"$OUT/changes.stdout" 2>>"$LOG"
STATUS=$?
set -e

cat "$OUT/changes.stdout" >>"$LOG"
echo "$(date -u +%FT%TZ) finished with status $STATUS" >>"$LOG"

# The change summary on stdout is what cron mails, or what you pipe into
# Slack. Anything a human should read goes here and nowhere else.
cat "$OUT/changes.stdout"
rm -f "$OUT/changes.stdout"

exit $STATUS
