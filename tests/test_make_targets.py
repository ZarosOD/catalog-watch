"""What the `make` targets are allowed to do to `out/`.

The bug this exists to prevent landed in feed-clean, not here: `demo/setup.sh`
ended with `rm -rf demo/.scratch out`, and the Makefile makes `setup` a
prerequisite of `run`, `watch`, `test` and `fixtures`. So `make run` wrote three
files and `make test` silently deleted them.

This repo never had the deletion, but as of THE-48 it has the other half of the
contract -- `demo/setup.sh --fresh`, and `demo/record.sh` calling it -- and a
contract nothing tests is the thing THE-48 was filed about. `--fresh` here is
load-bearing rather than ceremonial: `demo/demo.tape` films `ls out/`, so a file
left behind by an older run appears in the clip as though this morning's run
produced it.

Nothing in the unit suite could see any of this, because it happens in the
prerequisite, before pytest starts. These tests drive `make` itself in a copy of
the repo, which is the only level it was ever visible from.

The copy is what makes them safe to run: `--fresh` really does `rm -rf out`, so
pointing it at the developer's own checkout would destroy the output they were
looking at. The copy symlinks `.venv` back to the real one rather than building
its own, which keeps each test well under a second and needs no network.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
OUTPUT_FILES = ("products.csv", "products.xlsx", "changes.txt")

# Everything the copy either cannot use or should not inherit: the venv is
# symlinked in afterwards, and out/ has to start absent so its reappearance
# means `make run` created it. "out" also matches demo/out, which is 2.4 MB of
# committed clip these tests have no use for. demo/.scratch is excluded for the
# same reason as out/ -- a copy that inherited one from a recording would leave
# the scratch test asserting a deletion it did not cause.
SKIP = shutil.ignore_patterns(
    ".venv", ".git", "out", "out-terminal", ".scratch", "__pycache__",
    ".pytest_cache", "*.egg-info", ".toolchain",
)

pytestmark = [
    pytest.mark.skipif(shutil.which("make") is None, reason="these tests drive make"),
    pytest.mark.skipif(
        not (REPO / ".venv" / "bin" / "python").exists(),
        reason="no .venv to lend the copy (setup.sh builds one before pytest runs)",
    ),
]


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A throwaway copy of the repo with no out/ and a borrowed venv."""
    root = tmp_path / "catalog-watch"
    shutil.copytree(REPO, root, ignore=SKIP, symlinks=True)
    (root / ".venv").symlink_to(REPO / ".venv")
    assert not (root / "out").exists()
    return root


def make(checkout: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # pytest may itself have been started by `make test`; handing its jobserver
    # down to a nested make produces warnings and, worse, a shared job slot.
    env.pop("MAKEFLAGS", None)
    env.pop("MAKELEVEL", None)
    # `make test` in the copy would otherwise re-run this file, which would copy
    # the repo again, and so on. Collection still loads conftest and every test
    # module, and still runs the `setup` prerequisite -- which is the part these
    # tests are about -- so the target is exercised where it matters.
    env["PYTEST_ADDOPTS"] = "--collect-only -q"
    return subprocess.run(
        ["make", *args], cwd=checkout, capture_output=True, text=True, env=env
    )


def setup_sh(checkout: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["./demo/setup.sh", *args], cwd=checkout, capture_output=True, text=True
    )


def out_files(checkout: Path) -> set[str]:
    out = checkout / "out"
    return {p.name for p in out.iterdir()} if out.is_dir() else set()


def test_run_writes_the_output_files(checkout: Path) -> None:
    result = make(checkout, "run")

    assert result.returncode == 0, result.stderr
    assert out_files(checkout) >= set(OUTPUT_FILES)


@pytest.mark.parametrize("target", ["watch", "test", "fixtures"])
def test_other_targets_leave_the_output_alone(checkout: Path, target: str) -> None:
    assert make(checkout, "run").returncode == 0
    before = out_files(checkout)
    assert before >= set(OUTPUT_FILES)
    # A file nothing regenerates: if out/ is removed and rebuilt rather than
    # left alone, the three real files come back and this one does not.
    (checkout / "out" / "sentinel.txt").write_text("mine", encoding="utf-8")

    result = make(checkout, target)

    assert result.returncode == 0, result.stdout + result.stderr
    assert out_files(checkout) >= before | {"sentinel.txt"}
    assert (checkout / "out" / "sentinel.txt").read_text(encoding="utf-8") == "mine"


def test_setup_run_directly_leaves_the_output_alone(checkout: Path) -> None:
    """The second way the bug reproduced in feed-clean: no make involved."""
    assert make(checkout, "run").returncode == 0
    before = out_files(checkout)

    result = setup_sh(checkout)

    assert result.returncode == 0, result.stderr
    assert out_files(checkout) == before


def test_setup_fresh_removes_the_output(checkout: Path) -> None:
    """The recording path still gets its empty repo -- record.sh passes --fresh,
    and demo.tape films `ls out/`."""
    assert make(checkout, "run").returncode == 0
    assert (checkout / "out").is_dir()

    result = setup_sh(checkout, "--fresh")

    assert result.returncode == 0, result.stderr
    assert not (checkout / "out").exists()


def test_setup_clears_its_own_scratch_either_way(checkout: Path) -> None:
    """demo/.scratch is where the Playwright scene runs the tool -- the demo's
    own workspace, not anyone's output -- so it always goes."""
    scratch = checkout / "demo" / ".scratch"
    scratch.mkdir(parents=True)
    (scratch / "leftover").write_text("x", encoding="utf-8")

    assert setup_sh(checkout).returncode == 0

    assert not scratch.exists()


def test_setup_rejects_an_unknown_argument(checkout: Path) -> None:
    """A typo'd flag must not read as "no flag" and quietly skip the wipe.

    Before THE-48 this repo's setup.sh parsed no arguments at all, so every
    typo was silently ignored -- and so, for two months, was the --fresh it
    was never taught to accept."""
    result = setup_sh(checkout, "--clean")

    assert result.returncode == 2
    assert "--fresh" in result.stderr


def test_record_sh_asks_setup_for_a_fresh_start() -> None:
    """The wiring the two setup.sh tests above cannot reach.

    Running record.sh for real means downloading vhs, ttyd, ffmpeg and a
    headless Chromium, which is `make demo`'s job and not a unit test's. What
    is checkable here is that the one caller entitled to the wipe still asks
    for it, so the recording does not quietly start on stale output.
    """
    line = next(
        line
        for line in (REPO / "demo" / "record.sh").read_text(encoding="utf-8").splitlines()
        if "setup.sh" in line and not line.lstrip().startswith("#")
    )

    assert line.strip() == '"$DEMO_DIR/setup.sh" --fresh'
