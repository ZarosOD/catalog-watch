#!/usr/bin/env python3
"""The recorded scene. EDIT THIS FILE for a new piece — it is the Playwright
equivalent of a VHS tape.

Four beats, about 29 seconds:

  1. The storefront as it was yesterday morning.
  2. The same page today. Deliberately no annotation: the point is that the
     changes are not obvious by eye.
  3. The same page with the changes marked. The marks are driven by
     out/products.csv, which the tool wrote seconds earlier — nothing here
     knows what changed except by reading the tool's own output.
  4. out/changes.txt, the file the scheduled run leaves behind.

Everything is served from fixtures/ on localhost. No live site is contacted and
no real product, vendor or client data appears on screen.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from catalog_watch.serve import serve_directory  # noqa: E402

VIEWPORT = {"width": 1024, "height": 800}

# Seconds per beat. Keep the total under the 35s record.sh enforces.
HOLD_YESTERDAY = 6.5
HOLD_TODAY = 4.5
HOLD_MARKED = 6.0
HOLD_REPORT = 11.0

BANNER_CSS = """
  body { padding-top: 56px !important; }
  #cw-banner {
    position: fixed; top: 0; left: 0; right: 0; height: 56px; z-index: 9999;
    display: flex; align-items: center; gap: 14px; padding: 0 26px;
    background: #0f1720; color: #fff; font: 600 19px/1 -apple-system,
      "Segoe UI", Roboto, "DejaVu Sans", Arial, sans-serif;
    box-shadow: 0 2px 10px rgba(0,0,0,.25);
  }
  #cw-banner .cw-when { color: #7fd1a6; font-variant-numeric: tabular-nums; }
  #cw-banner .cw-what { color: #e8eef5; font-weight: 500; }
  .cw-mark { outline: 3px solid #d9534f; outline-offset: 2px; position: relative; }
  .cw-mark.cw-down { outline-color: #1a7f4b; }
  .cw-badge {
    position: absolute; top: -12px; right: 10px; z-index: 20;
    background: #d9534f; color: #fff; border-radius: 11px;
    padding: 3px 11px; font-size: 12px; font-weight: 700; letter-spacing: .3px;
    white-space: nowrap;
  }
  .cw-mark.cw-down .cw-badge { background: #1a7f4b; }
"""

BANNER_JS = """
([when, what]) => {
  document.getElementById('cw-banner')?.remove();
  const bar = document.createElement('div');
  bar.id = 'cw-banner';
  bar.innerHTML = `<span class="cw-when"></span><span class="cw-what"></span>`;
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

REPORT_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>out/changes.txt</title>
  <style>
    body {{
      margin: 0; background: #0f1720; color: #e8eef5; padding: 26px 40px;
      font: 15px/1.5 -apple-system, "Segoe UI", Roboto, "DejaVu Sans", Arial, sans-serif;
    }}
    h1 {{ font-size: 17px; margin: 0 0 4px; color: #7fd1a6; }}
    p.sub {{ margin: 0 0 18px; color: #8aa0b4; font-size: 14px; }}
    pre {{
      margin: 0; background: #16202b; border: 1px solid #24313f; border-radius: 8px;
      padding: 20px 24px; font: 13.5px/1.7 ui-monospace, "DejaVu Sans Mono",
      "SF Mono", Menlo, Consolas, monospace; color: #dfe8f1;
      white-space: pre; overflow: hidden;
    }}
    .files {{ margin-top: 16px; color: #8aa0b4; font-size: 13px; }}
    .files code {{ color: #e8eef5; }}
  </style>
</head>
<body>
  <h1>out/changes.txt</h1>
  <p class="sub">written by the 06:00 run, alongside products.csv and products.xlsx</p>
  <pre>{report}</pre>
  <p class="files">Same run also wrote <code>out/products.csv</code> and
     <code>out/products.xlsx</code> (Changes sheet first).</p>
</body>
</html>
"""


def run_the_tool(scratch: Path) -> tuple[dict[str, str], str]:
    """Two real runs of watch.py, a day apart. Returns the marks to draw and
    the report text to show — both read back out of what the tool wrote."""
    out = scratch / "out"
    state = scratch / "state.json"

    for day in ("site", "site-day2"):
        subprocess.run(
            [
                sys.executable,
                "watch.py",
                "--serve",
                f"fixtures/{day}",
                "--state",
                str(state),
                "--out",
                str(out),
                "--quiet",
            ],
            cwd=REPO,
            check=True,
        )

    marks: dict[str, str] = {}
    with (out / "products.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["change"]:
                marks[row["sku"]] = row["change"]

    return marks, (out / "changes.txt").read_text(encoding="utf-8")


def beat(page, when: str, what: str, hold: float) -> None:
    page.add_style_tag(content=BANNER_CSS)
    page.evaluate(BANNER_JS, [when, what])
    page.wait_for_timeout(hold * 1000)


def record(video_dir: Path) -> Path:
    from playwright.sync_api import sync_playwright

    scratch = REPO / "demo" / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    marks, report_text = run_the_tool(scratch)

    report_dir = scratch / "report"
    report_dir.mkdir(exist_ok=True)
    (report_dir / "index.html").write_text(
        REPORT_PAGE.format(report=escape(report_text.rstrip())), encoding="utf-8"
    )

    with (
        serve_directory(REPO / "fixtures" / "site") as yesterday,
        serve_directory(REPO / "fixtures" / "site-day2") as today,
        serve_directory(report_dir) as report_url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(video_dir),
            record_video_size=VIEWPORT,
            device_scale_factor=1,
        )
        page = context.new_page()

        page.goto(yesterday, wait_until="networkidle")
        beat(page, "Mon 06:00", "yesterday's catalogue", HOLD_YESTERDAY)

        page.goto(today, wait_until="networkidle")
        beat(page, "Tue 06:00", "the same page this morning. Spot the difference?", HOLD_TODAY)

        page.evaluate(MARK_JS, marks)
        beat(
            page,
            "Tue 06:00",
            f"catalog-watch found {len(marks)} changes, unprompted",
            HOLD_MARKED,
        )

        page.goto(report_url, wait_until="networkidle")
        page.wait_for_timeout(HOLD_REPORT * 1000)

        path = Path(page.video.path())
        context.close()
        browser.close()

    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    args.video_dir.mkdir(parents=True, exist_ok=True)
    path = record(args.video_dir)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
