#!/usr/bin/env python3
"""The recorded scene. EDIT THIS FILE for a new piece — it is the Playwright
equivalent of a VHS tape. The grid frames are not built here: demo/lib/sheet.py
is shared by all four pieces and renders every spreadsheet frame in the
portfolio.

Five beats, about 21 seconds, in the one shape all four clips use. This piece
is the one whose input really is a web page, so its BEFORE is the storefront
rather than a grid — the same claim the others make (this is the real input,
read at record time), about a different kind of input:

  1. BEFORE   the storefront as it was yesterday morning.
  2. BEFORE   the same page today. Deliberately no annotation: the point is
              that the changes are not obvious by eye.
  3. COMMAND  the morning run, and the real stdout it printed.
  4. AFTER    the same page with the changes marked. The marks are driven by
              out/products.csv, which the run above wrote seconds earlier —
              nothing here knows what changed except by reading the tool's own
              output.
  5. AFTER    out/products.xlsx in the grid, Changes sheet: the file the
              scheduled run leaves behind, opened.

Everything is served from fixtures/ on localhost. No live site is contacted and
no real product, vendor or client data appears on screen.

Ahead of beat 1, `demo/lib/card.py` prepends a 0.8 s title card composed from
two of the frames below — the before artifact on the left, the after one on the
right. It is not a beat: the scene is unchanged and the card is a prepend plus
a `demo/out/poster.png` export. The two labels and the two lines of specifics
under them are the only part of it that belongs to this piece, and they are
just below.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "demo" / "lib"))

import sheet  # noqa: E402

from catalog_watch.serve import serve_directory  # noqa: E402

# The storefront beats share the BEFORE budget; the marked page and the grid
# share the AFTER one. This clip's timings are the shared ones divided, not a
# second set of numbers.
HOLD_YESTERDAY = sheet.HOLD_BEFORE / 2
HOLD_TODAY = sheet.HOLD_BEFORE / 2
HOLD_MARKED = sheet.HOLD_AFTER * 0.45
HOLD_GRID = sheet.HOLD_AFTER * 0.55

CHANGE_COLUMNS = ["kind", "sku", "name", "before", "after", "detail"]
WIDTHS = {"name": 2.0, "detail": 2.4, "kind": 0.9, "sku": 0.9}

BANNER_CSS = f"""
  body {{ padding-top: 56px !important; }}
  #cw-banner {{
    position: fixed; top: 0; left: 0; right: 0; height: 56px; z-index: 9999;
    display: flex; align-items: center; gap: 14px; padding: 0 26px;
    background: #0f1720; color: #fff; font: 600 19px/1 {sheet.SANS};
    box-shadow: 0 2px 10px rgba(0,0,0,.25);
  }}
  #cw-banner .cw-step {{
    font-size: 12.5px; font-weight: 700; letter-spacing: 1.6px; color: #0f1720;
    background: #cdd3e4; border-radius: 4px; padding: 4px 9px;
  }}
  #cw-banner .cw-step.after {{ background: #7fd1a6; }}
  #cw-banner .cw-when {{ color: #7fd1a6; font-variant-numeric: tabular-nums; }}
  #cw-banner .cw-what {{ color: #e8eef5; font-weight: 500; }}
  .cw-mark {{ outline: 3px solid #d9534f; outline-offset: 2px; position: relative; }}
  .cw-mark.cw-down {{ outline-color: #1a7f4b; }}
  .cw-badge {{
    position: absolute; top: -12px; right: 10px; z-index: 20;
    background: #d9534f; color: #fff; border-radius: 11px;
    padding: 3px 11px; font-size: 12px; font-weight: 700; letter-spacing: .3px;
    white-space: nowrap;
  }}
  .cw-mark.cw-down .cw-badge {{ background: #1a7f4b; }}
"""

BANNER_JS = """
([step, when, what]) => {
  document.getElementById('cw-banner')?.remove();
  const bar = document.createElement('div');
  bar.id = 'cw-banner';
  bar.innerHTML = `<span class="cw-step"></span><span class="cw-when"></span>`
                + `<span class="cw-what"></span>`;
  const tag = bar.querySelector('.cw-step');
  tag.textContent = step;
  if (step === 'AFTER') tag.classList.add('after');
  bar.querySelector('.cw-when').textContent = when;
  bar.querySelector('.cw-what').textContent = what;
  document.body.prepend(bar);
}
"""

MARK_JS = """
(marks) => {
  for (const [sku, label] of Object.entries(marks)) {
    const tag = [...document.querySelectorAll('.sku')]
      .find(el => el.textContent.trim() === sku);
    if (!tag) continue;
    const card = tag.closest('.product');
    if (!card) continue;
    card.classList.add('cw-mark');
    if (label === 'price cut') card.classList.add('cw-down');
    const badge = document.createElement('span');
    badge.className = 'cw-badge';
    badge.textContent = label;
    card.appendChild(badge);
  }
}
"""


def here(path: Path) -> str:
    """A path as the argv on screen should carry it: relative to the repo.

    Both runs below are `cwd=REPO`, so the relative form names the same file.
    The absolute one names *this box* — `/home/<someone>/…` is a username and a
    directory layout, on an asset that goes to clients, and at 185 characters it
    ran off the right edge of the terminal panel as well (THE-261). Derived from
    the same Path the scene reads afterwards rather than written out a second
    time, so what runs and what is read cannot drift apart."""
    return str(path.relative_to(REPO))


def baseline(out: Path, state: Path) -> None:
    """Yesterday's run, off camera. A change report needs something to compare
    against, and the first run of anything has nothing."""
    sheet.run_command(
        [sys.executable, "watch.py", "--serve", "fixtures/site",
         "--state", here(state), "--out", here(out), "--quiet"],
        cwd=REPO,
    )


def marks_from_output(out: Path) -> dict[str, str]:
    """What to draw on the page, read out of the CSV the tool just wrote."""
    found: dict[str, str] = {}
    with (out / "products.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["change"]:
                found[row["sku"]] = row["change"]
    return found


def banner(page, step: str, when: str, what: str, hold: float) -> None:
    page.add_style_tag(content=BANNER_CSS)
    page.evaluate(BANNER_JS, [step, when, what])
    page.wait_for_timeout(hold * 1000)


# The title card's two labels. Its shape, colours and typeface are
# demo/lib/card.py, which is shared and byte-identical in all four repos; the
# words are here because what this piece turns its input into is a fact about
# this piece, not about the pipeline.
# The AFTER line counts the changes the run actually found, so the card
# cannot claim a number the clip does not show.
CARD_BEFORE_LABEL = "This morning's storefront"
CARD_AFTER_LABEL = "Every change, marked"


def record(video_dir: Path, poster: Path | None = None) -> Path:
    scratch = REPO / "demo" / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    out, state = REPO / "out", scratch / "state.json"

    baseline(out, state)

    with (
        serve_directory(REPO / "fixtures" / "site") as yesterday,
        serve_directory(REPO / "fixtures" / "site-day2") as today,
        sheet.Scene(video_dir, poster=poster) as scene,
    ):
        scene.goto(yesterday, 0)
        banner(scene.page, "BEFORE", "Mon 06:00", "yesterday's catalogue",
               HOLD_YESTERDAY)

        scene.goto(today, 0)
        banner(scene.page, "BEFORE", "Tue 06:00",
               "the same page this morning. Spot the difference?", HOLD_TODAY)
        # selector=None: this piece's frame is a served page, not one of
        # sheet.py's grids, so the panel is the whole viewport. The card's two
        # halves are then the same page before and after marking, which is
        # what this piece is for.
        scene.panel(
            "before", CARD_BEFORE_LABEL,
            "identical to yesterday by eye | prices, stock and names all move quietly",
            selector=None,
        )

        # This morning's run, on camera. The marks and the grid below both come
        # out of what it writes, so neither can show a change it did not find.
        command = sheet.run_command(
            [sys.executable, "watch.py", "--serve", "fixtures/site-day2",
             "--state", here(state), "--out", here(out), "--report", "--quiet"],
            cwd=REPO,
        )
        scene.show(
            sheet.terminal_html(command, said="one command, every morning, on a timer"),
            sheet.HOLD_COMMAND,
        )

        marks = marks_from_output(out)
        scene.goto(today, 0)
        scene.page.evaluate(MARK_JS, marks)
        banner(scene.page, "AFTER", "Tue 06:00",
               f"{len(marks)} changes, found unprompted", HOLD_MARKED)
        scene.panel(
            "after", CARD_AFTER_LABEL,
            f"{len(marks)} found unprompted | logged to products.xlsx, Changes sheet",
            selector=None,
        )

        changes = sheet.read_table(out / "products.xlsx", "Changes", base=REPO)
        scene.show(
            sheet.grid_html(
                sheet.view(changes, CHANGE_COLUMNS, widths=WIDTHS),
                step="AFTER",
                said="out/products.xlsx — the file the 06:00 run leaves behind",
            ),
            HOLD_GRID,
        )

    return scene.video_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-dir", required=True, type=Path)
    parser.add_argument("--poster", type=Path,
                        help="write the title card here as PNG (demo/lib/card.py)")
    args = parser.parse_args(argv)

    args.video_dir.mkdir(parents=True, exist_ok=True)
    print(record(args.video_dir, args.poster))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
