#!/usr/bin/env bash
# Project-specific preparation, run by demo/record.sh before the recipe.
# EDIT THIS FILE for a new portfolio piece: it is the only place that knows the
# project is Python.
#
# It must be safe to run repeatedly and must leave the repo ready to record.

set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$DEMO_DIR/.." && pwd)"
cd "$REPO_ROOT"

VENV=".venv"
PY="$VENV/bin/python"

log() { printf '  %s\n' "$*" >&2; }

# Generic: fetches a pinned uv if the machine has none. See lib/uv.sh.
# shellcheck source=lib/uv.sh
. "$DEMO_DIR/lib/uv.sh"

if [ ! -x "$PY" ]; then
  if UV="$(ensure_uv)"; then
    log "creating $VENV with uv"
    # --python 3.12 lets uv supply the interpreter when the machine has no
    # 3.12 of its own, which is the whole point of bootstrapping it.
    "$UV" venv --python 3.12 "$VENV" >/dev/null
    VIRTUAL_ENV="$REPO_ROOT/$VENV" "$UV" pip install --quiet -e '.[dev]'
  elif python3 -m venv --help >/dev/null 2>&1 && python3 -c 'import ensurepip' 2>/dev/null; then
    log "creating $VENV with python -m venv"
    python3 -m venv "$VENV"
    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install --quiet -e '.[dev]'
  else
    # Last resort: we could neither fetch uv nor use the system python.
    echo "setup.sh: could not fetch uv (see the log above) and this python3 has no" >&2
    echo "  ensurepip. Install uv (https://astral.sh/uv) or your distro's python3-venv" >&2
    echo "  package, then re-run." >&2
    exit 1
  fi
fi

if ! "$PY" -c 'import bs4, openpyxl' 2>/dev/null; then
  echo "setup.sh: $VENV exists but the dependencies are missing; delete $VENV and re-run" >&2
  exit 1
fi

# The fixture storefront is committed, but regenerate it if the checkout lacks it.
if [ ! -f fixtures/site/index.html ] || [ ! -f fixtures/site-day2/index.html ]; then
  log "generating the synthetic storefront"
  "$PY" fixtures/generate_site.py >/dev/null
fi

# Nothing from a previous run should appear in the recording: the scene starts
# from no state at all, so the first run really is a first run.
rm -rf demo/.scratch
