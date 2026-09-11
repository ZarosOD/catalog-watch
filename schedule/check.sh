#!/usr/bin/env bash
# Prove the scheduled run actually works, rather than asserting that it does.
#
# Two things break scheduled jobs and neither shows up when you test by hand:
#
#   1. cron runs with an almost empty environment. No PATH beyond /usr/bin:/bin,
#      no VIRTUAL_ENV, no cwd. `env -i` below reproduces that exactly.
#   2. "it diffs against the last run" is easy to claim and easy to get wrong.
#      So this runs twice — yesterday's catalogue, then today's — against a
#      throwaway state file, and checks the second run reports only the deltas.
#
#   ./schedule/check.sh        (or: make schedule-check)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }

# cron's environment, near enough: nothing inherited but HOME, PATH and SHELL.
as_cron() {
  env -i \
    HOME="$HOME" \
    PATH=/usr/bin:/bin \
    SHELL=/bin/sh \
    CATALOG_WATCH_TARGET="--serve $1" \
    CATALOG_WATCH_STATE="$WORK/state.json" \
    CATALOG_WATCH_OUT="$WORK/out" \
    CATALOG_WATCH_LOG_DIR="$WORK/logs" \
    /bin/bash "$REPO_ROOT/schedule/run.sh"
}

say "run 1 under cron's environment: yesterday's catalogue"
FIRST="$(as_cron fixtures/site)" || fail "the first scheduled run exited non-zero"
echo "$FIRST" | sed 's/^/    /'

grep -q "First run" <<<"$FIRST" || fail "run 1 should have reported a baseline"

say "run 2 under cron's environment: this morning's catalogue"
SECOND="$(as_cron fixtures/site-day2)" || fail "the second scheduled run exited non-zero"
echo "$SECOND" | sed 's/^/    /'

grep -qE "[0-9]+ changes since the previous run" <<<"$SECOND" \
  || fail "run 2 should have reported changes against run 1"

# The whole promise of a scheduled report: the second run talks about what
# moved, not about the other 25 products that did not.
REPORTED="$(grep -cE '^  (price|stock|new|delisted|renamed)' <<<"$SECOND" || true)"
[ "$REPORTED" -gt 0 ] || fail "run 2 listed no changed products"
[ "$REPORTED" -lt 10 ] || fail "run 2 listed $REPORTED products; that is not a delta report"

say "run 3 under cron's environment: nothing changed since run 2"
THIRD="$(as_cron fixtures/site-day2)" || fail "the third scheduled run exited non-zero"
grep -q "No changes since the previous run." <<<"$THIRD" \
  || fail "run 3 should have reported no changes"

for artefact in products.csv products.xlsx changes.txt; do
  [ -s "$WORK/out/$artefact" ] || fail "the scheduled run left no $artefact"
done
[ -s "$WORK/logs/catalog-watch.log" ] || fail "the scheduled run left no log"

printf '\n\033[1;32mOK\033[0m  3 runs under `env -i`: baseline, %s deltas, then nothing.\n' "$REPORTED"
printf '    Artefacts and a log were written each time. Install it with one of:\n'
printf '      crontab:  schedule/catalog-watch.cron\n'
printf '      systemd:  schedule/catalog-watch.service + .timer\n'
