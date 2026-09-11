#!/usr/bin/env python3
"""Write the two revisions of the synthetic storefront, and the ground truth
the tests assert against, from one table.

Everything here is invented. Tidewater Supply Co. is not a company, the SKUs
are made up, and the prices came out of this file. No real catalogue, vendor or
client data is in this repo or in the recording.

Why a bundled fixture rather than a live site: a demo that hammers somebody
else's storefront is a liability, a live site breaks the recording the week it
redesigns, and a local fixture makes the run-to-run diff deterministic — which
is the entire point of the tool. Pointing this at a real catalogue is a URL and
a site profile, not a code change.

    python fixtures/generate_site.py

writes fixtures/site/ (day one), fixtures/site-day2/ (the next morning) and
tests/expected_changes.json.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

STORE = "Tidewater Supply Co."
PAGE_SIZE = 9

# sku, name, price, stock. "Call for pricing" is a string on purpose: it is the
# product whose price cannot be read, and it stays unreadable on both days so
# it shows up as a standing review flag rather than as a change.
PRODUCTS: list[tuple[str, str, object, str]] = [
    ("TW-1004", "Braided Dock Line, 12mm x 9m", "48.00", "In stock"),
    ("TW-1011", "Braided Dock Line, 16mm x 15m", "79.50", "In stock"),
    ("TW-1020", "Anchor Rode, 8mm chain x 6m", "134.00", "In stock"),
    ("TW-1033", "Stainless Bow Shackle, 10mm", "12.75", "In stock"),
    ("TW-1041", "Stainless Bow Shackle, 16mm", "24.40", "In stock"),
    ("TW-1055", "Cleat, Open Base, 200mm", "31.20", "In stock"),
    ("TW-1062", "Cleat, Open Base, 300mm", "44.90", "Out of stock"),
    ("TW-1078", "Fender, Cylindrical, 150 x 580mm", "56.00", "In stock"),
    ("TW-1084", "Fender, Cylindrical, 200 x 700mm", "88.25", "In stock"),
    ("TW-1090", "Fender Cover, Acrylic, Pair", "39.00", "In stock"),
    ("TW-1107", "Bilge Pump, 800 GPH", "62.50", "In stock"),
    ("TW-1115", "Bilge Pump, 1500 GPH", "104.00", "Back-order"),
    ("TW-1123", "Float Switch, Marine Grade", "37.80", "In stock"),
    ("TW-1130", "Deck Hatch, 450 x 450mm", "Call for pricing", "In stock"),
    ("TW-1146", "Hatch Seal Kit, 6m", "27.60", "In stock"),
    ("TW-1152", "Navigation Light, Bi-colour", "51.40", "In stock"),
    ("TW-1168", "Navigation Light, Stern, 12V", "42.90", "In stock"),
    ("TW-1175", "Masthead Anchor Light, LED", "96.00", "In stock"),
    ("TW-2003", "Marine Battery Isolator, 300A", "119.00", "In stock"),
    ("TW-2010", "Battery Box, Vented, Group 27", "48.70", "In stock"),
    ("TW-2026", "Tinned Marine Cable, 6mm² x 10m", "58.30", "In stock"),
    ("TW-2034", "Heat-Shrink Ring Terminals, 50ct", "22.15", "In stock"),
    ("TW-2049", "Through-Hull Skin Fitting, 25mm", "33.60", "In stock"),
    ("TW-2057", "Seacock, Bronze, 25mm", "87.40", "In stock"),
    ("TW-2063", "Hose Clamp, 316 Stainless, 10ct", "18.90", "In stock"),
    ("TW-2071", "Sanitation Hose, 38mm x 5m", "74.25", "In stock"),
    ("TW-2088", "Antifouling Primer, 2.5L", "68.00", "In stock"),
    ("TW-2094", "Teak Cleaner, 1L", "19.50", "In stock"),
    ("TW-2101", "Stainless Polish, 500ml", "14.80", "In stock"),
    ("TW-2118", "Winch Service Kit, Size 40", "63.00", "Pre-order"),
]

# What the overnight catalogue update did. One of each thing the diff can see.
PRICE_EDITS: dict[str, str] = {
    "TW-1004": "41.50",  # cut
    "TW-1084": "79.95",  # cut
    "TW-2057": "94.80",  # rise
}
STOCK_EDITS: dict[str, str] = {
    "TW-1078": "Out of stock",
}
DELISTED = "TW-2101"
NEW_PRODUCT = ("TW-2125", "Storm Jib Sheet, 10mm x 12m", "57.40", "In stock")


def day_one() -> list[tuple[str, str, object, str]]:
    return list(PRODUCTS)


def day_two() -> list[tuple[str, str, object, str]]:
    rows = []
    for sku, name, price, stock in PRODUCTS:
        if sku == DELISTED:
            continue
        rows.append(
            (sku, name, PRICE_EDITS.get(sku, price), STOCK_EDITS.get(sku, stock))
        )
    rows.append(NEW_PRODUCT)
    return rows


def tone(sku: str) -> int:
    """A stable thumbnail hue per sku, so regenerating the site does not churn
    the diff or the recording."""
    return sum(ord(c) for c in sku) % 8


def money(price: object) -> str:
    return price if isinstance(price, str) and not price[0].isdigit() else f"${price}"


def stock_class(stock: str) -> str:
    return {
        "In stock": "ok",
        "Out of stock": "no",
        "Back-order": "wait",
        "Pre-order": "wait",
    }.get(stock, "wait")


def card(sku: str, name: str, price: object, stock: str) -> str:
    return f"""      <article class="product">
        <div class="thumb tone-{tone(sku)}"></div>
        <h2 class="product-name">{name}</h2>
        <p class="sku">{sku}</p>
        <p class="price">{money(price)}</p>
        <p class="stock {stock_class(stock)}">{stock}</p>
        <a class="product-link" href="products/{sku}.html">Details</a>
      </article>"""


def page(
    title: str, rows: list[tuple[str, str, object, str]], number: int, total: int
) -> str:
    cards = "\n".join(card(*row) for row in rows)
    nav = []
    if number > 1:
        previous = "index.html" if number == 2 else f"page{number - 1}.html"
        nav.append(f'<a class="prev" href="{previous}">← Previous</a>')
    if number < total:
        nav.append(f'<a class="next" href="page{number + 1}.html">Next →</a>')
    nav_html = f'    <nav class="pager">{" ".join(nav)}</nav>\n' if nav else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{STORE} — {title}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="masthead">
    <div class="brand">{STORE}</div>
    <div class="tagline">Chandlery &amp; deck hardware — trade catalogue</div>
  </header>
  <main>
    <h1 class="catalogue-title">{title}<span class="page-of">page {number} of {total}</span></h1>
    <section class="grid">
{cards}
    </section>
{nav_html}  </main>
  <footer>Synthetic sample data. {STORE} is not a real company.</footer>
</body>
</html>
"""


def detail_page(sku: str, name: str, price: object, stock: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{STORE} — {name}</title>
  <link rel="stylesheet" href="../style.css">
</head>
<body>
  <header class="masthead"><div class="brand">{STORE}</div></header>
  <main class="detail">
    <div class="thumb tone-{tone(sku)}"></div>
    <h1 class="product-name">{name}</h1>
    <p class="sku">{sku}</p>
    <p class="price">{money(price)}</p>
    <p class="stock {stock_class(stock)}">{stock}</p>
    <a class="product-link" href="../index.html">← Back to the catalogue</a>
  </main>
  <footer>Synthetic sample data.</footer>
</body>
</html>
"""


STYLE = """/* Deliberately plain and high-contrast: this page is recorded, and a
   screenshot has to stay legible after it is scaled into a README. */
:root {
  --ink: #16202b;
  --muted: #63748a;
  --line: #d7dee7;
  --ok: #1a7f4b;
  --no: #b4302c;
  --wait: #9a6a12;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font: 16px/1.45 -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  color: var(--ink);
  background: #f4f6f9;
}
.masthead {
  background: #16202b;
  color: #fff;
  padding: 18px 32px;
  display: flex;
  align-items: baseline;
  gap: 18px;
}
.brand { font-size: 22px; font-weight: 700; letter-spacing: .2px; }
.tagline { color: #9fb2c6; font-size: 14px; }
main { padding: 24px 32px 40px; max-width: 1180px; margin: 0 auto; }
.catalogue-title {
  font-size: 19px; margin: 4px 0 20px; display: flex;
  align-items: baseline; justify-content: space-between;
  border-bottom: 1px solid var(--line); padding-bottom: 10px;
}
.page-of { font-size: 14px; font-weight: 400; color: var(--muted); }
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.product {
  background: #fff; border: 1px solid var(--line); border-radius: 8px;
  padding: 14px 16px 16px; display: grid;
  grid-template-columns: 56px 1fr; grid-template-rows: auto auto auto;
  column-gap: 14px; align-items: start;
}
.thumb { grid-row: 1 / 4; width: 56px; height: 56px; border-radius: 6px; }
.tone-0 { background: #c7d7e6; } .tone-1 { background: #d4dfc9; }
.tone-2 { background: #e6d9c2; } .tone-3 { background: #cdd3e4; }
.tone-4 { background: #dccfd9; } .tone-5 { background: #c4dcd8; }
.tone-6 { background: #e3d5c7; } .tone-7 { background: #d0dae3; }
.product-name { font-size: 15px; font-weight: 600; margin: 0; line-height: 1.3; }
.sku { grid-column: 2; margin: 3px 0 0; font: 12px/1 ui-monospace, "SF Mono", Menlo, Consolas, monospace; color: var(--muted); }
.price { grid-column: 2; margin: 8px 0 0; font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; }
.stock { grid-column: 2; margin: 4px 0 0; font-size: 13px; font-weight: 600; }
.stock.ok { color: var(--ok); } .stock.no { color: var(--no); } .stock.wait { color: var(--wait); }
.product-link { grid-column: 2; margin-top: 6px; font-size: 13px; color: #2b6cb0; }
.pager { margin-top: 22px; display: flex; gap: 18px; font-size: 15px; }
.pager a { color: #2b6cb0; text-decoration: none; font-weight: 600; }
.detail { max-width: 520px; }
.detail .product-name { font-size: 24px; margin-top: 16px; }
footer { padding: 16px 32px 32px; color: var(--muted); font-size: 13px; }
"""

# Disallow before Allow on purpose: Python's urllib.robotparser takes the first
# matching rule, not the longest, so a leading "Allow: /" would shadow
# everything after it. Most real robots.txt files are written this way too.
ROBOTS = """User-agent: *
Disallow: /cart/
Allow: /
Crawl-delay: 0.2

# Synthetic fixture. The point of this file is that catalog-watch reads it
# before the first request: it stops on a disallowed path, and it slows down to
# the crawl-delay the site asks for.
"""


def write_site(directory: Path, rows: list[tuple[str, str, object, str]], title: str) -> None:
    if directory.exists():
        shutil.rmtree(directory)
    (directory / "products").mkdir(parents=True)

    pages = [rows[i : i + PAGE_SIZE] for i in range(0, len(rows), PAGE_SIZE)]
    for index, chunk in enumerate(pages, start=1):
        name = "index.html" if index == 1 else f"page{index}.html"
        (directory / name).write_text(
            page(title, chunk, index, len(pages)), encoding="utf-8"
        )
    for row in rows:
        (directory / "products" / f"{row[0]}.html").write_text(
            detail_page(*row), encoding="utf-8"
        )
    (directory / "style.css").write_text(STYLE, encoding="utf-8")
    (directory / "robots.txt").write_text(ROBOTS, encoding="utf-8")


def expected_changes() -> dict:
    """The ground truth, written from the same table that drew the pages.

    The end-to-end test asserts against this, so it is checking the tool
    against the fixture rather than against its own output.
    """
    before = {row[0]: row for row in day_one()}
    after = {row[0]: row for row in day_two()}
    changes = []
    for sku in sorted(set(before) | set(after)):
        if sku not in before:
            changes.append({"kind": "new", "sku": sku})
        elif sku not in after:
            changes.append({"kind": "delisted", "sku": sku})
        else:
            if before[sku][2] != after[sku][2]:
                changes.append(
                    {
                        "kind": "price",
                        "sku": sku,
                        "before": before[sku][2],
                        "after": after[sku][2],
                    }
                )
            if before[sku][3] != after[sku][3]:
                changes.append(
                    {
                        "kind": "availability",
                        "sku": sku,
                        "before": before[sku][3],
                        "after": after[sku][3],
                    }
                )
    return {
        "day1_products": len(day_one()),
        "day2_products": len(day_two()),
        "unreadable_price_skus": [
            sku
            for sku, _, price, _ in day_one()
            if isinstance(price, str) and not price[0].isdigit()
        ],
        "changes": changes,
    }


def main() -> int:
    root = Path(__file__).resolve().parent
    repo = root.parent

    write_site(root / "site", day_one(), "Deck hardware & chandlery")
    write_site(root / "site-day2", day_two(), "Deck hardware & chandlery")

    truth = expected_changes()
    (repo / "tests" / "expected_changes.json").write_text(
        json.dumps(truth, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"fixtures/site/       {len(day_one())} products\n"
        f"fixtures/site-day2/  {len(day_two())} products\n"
        f"tests/expected_changes.json  {len(truth['changes'])} expected changes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
