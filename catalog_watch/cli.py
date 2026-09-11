"""Argument handling, the crawl loop, and the exit codes a scheduler reads."""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

from . import report, state
from .diff import compare
from .fetch import FetchError, Fetcher, RobotsDisallowed
from .models import Snapshot
from .scrape import count_unidentified, find_next_page, parse_products
from .serve import serve_directory
from .site import SiteConfig, SiteConfigError

EXIT_OK = 0
EXIT_REVIEW = 1
EXIT_CHANGED = 2
EXIT_USAGE = 3
EXIT_FETCH = 4

DEFAULT_SITE = "sites/fixture.json"
DEFAULT_STATE = "state/catalog.json"
DEFAULT_OUT = "out"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="watch.py",
        description=(
            "Scrape a product catalogue, compare it against the previous run, "
            "and write a CSV, an XLSX and a plain-text change summary."
        ),
        epilog=(
            "The bundled demo scrapes a synthetic storefront served from this "
            "repo (--serve fixtures/site). Pointing it at a real catalogue is a "
            "URL plus a site profile; see sites/fixture.json and the README."
        ),
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="catalogue URL to start from, e.g. https://shop.example.com/products",
    )
    parser.add_argument(
        "--serve",
        metavar="DIR",
        help="serve DIR on localhost and scrape that instead of a remote URL",
    )
    parser.add_argument("--site", default=DEFAULT_SITE, help=f"site profile JSON (default {DEFAULT_SITE})")
    parser.add_argument("--state", default=DEFAULT_STATE, help=f"snapshot file (default {DEFAULT_STATE})")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"output directory (default {DEFAULT_OUT})")
    parser.add_argument("--report", action="store_true", help="print the change summary to stdout")
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="seconds between requests (default 0.5 remote, 0 for --serve)",
    )
    parser.add_argument("--timeout", type=float, default=15.0, help="per-request timeout in seconds")
    parser.add_argument("--max-pages", type=int, default=None, help="override the profile's page cap")
    parser.add_argument(
        "--ignore-robots",
        action="store_true",
        help="scrape paths robots.txt disallows. Only with the site owner's agreement.",
    )
    parser.add_argument(
        "--no-state",
        action="store_true",
        help="report against the previous run but do not overwrite it (a dry run)",
    )
    parser.add_argument("--fail-on-review", action="store_true", help=f"exit {EXIT_REVIEW} if any product is flagged")
    parser.add_argument("--fail-on-change", action="store_true", help=f"exit {EXIT_CHANGED} if anything changed")
    parser.add_argument("--quiet", action="store_true", help="only print errors")
    return parser


def crawl(
    start_url: str, config: SiteConfig, fetcher: Fetcher, max_pages: int, log
) -> tuple[list, int, list[str]]:
    """Follow the catalogue's "next page" links, collecting products.

    Returns ``(products, pages_fetched, notes)``. Notes are things the operator
    should know that are not per-product issues: duplicate skus, cards with no
    sku, hitting the page cap.
    """
    products = []
    seen_skus: dict[str, int] = {}
    seen_urls: set[str] = set()
    notes: list[str] = []
    unidentified = 0
    url: str | None = start_url
    pages = 0

    while url and pages < max_pages:
        if url in seen_urls:
            notes.append(f"pagination looped back to {url}; stopped there")
            break
        seen_urls.add(url)

        html = fetcher.get(url)
        pages += 1
        log(f"  page {pages}: {url}")

        unidentified += count_unidentified(html, config)
        for product in parse_products(html, config, url):
            if product.sku in seen_skus:
                seen_skus[product.sku] += 1
                continue
            seen_skus[product.sku] = 1
            products.append(product)

        url = find_next_page(html, config, url)

    if url and pages >= max_pages:
        notes.append(
            f"stopped at the {max_pages}-page cap with more pages to go; "
            f"raise --max-pages if the catalogue is genuinely longer"
        )
    if unidentified:
        notes.append(
            f"{unidentified} product card(s) had no readable sku and were skipped; "
            f"check the 'sku' selector in the site profile"
        )
    duplicates = sum(count - 1 for count in seen_skus.values() if count > 1)
    if duplicates:
        notes.append(f"{duplicates} duplicate sku(s) across pages; the first listing won")

    return products, pages, notes


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = (lambda *_: None) if args.quiet else (lambda *m: print(*m, file=sys.stderr))

    if bool(args.url) == bool(args.serve):
        print(
            "watch.py: give either a URL or --serve DIR, not both and not neither.\n"
            "  try: watch.py --serve fixtures/site --report",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        config = SiteConfig.load(args.site)
    except SiteConfigError as exc:
        print(f"watch.py: {exc}", file=sys.stderr)
        return EXIT_USAGE

    delay = args.delay if args.delay is not None else (0.0 if args.serve else 0.5)
    max_pages = args.max_pages or config.max_pages
    fetcher = Fetcher(
        delay=delay, timeout=args.timeout, obey_robots=not args.ignore_robots
    )

    with contextlib.ExitStack() as stack:
        if args.serve:
            try:
                base_url = stack.enter_context(serve_directory(args.serve))
            except NotADirectoryError as exc:
                print(f"watch.py: {exc}", file=sys.stderr)
                return EXIT_USAGE
            log(f"serving {args.serve} at {base_url}")
        else:
            base_url = args.url

        log(f"scraping {config.name}")
        try:
            products, pages, notes = crawl(base_url, config, fetcher, max_pages, log)
        except RobotsDisallowed as exc:
            print(f"watch.py: {exc}", file=sys.stderr)
            return EXIT_FETCH
        except FetchError as exc:
            print(f"watch.py: {exc}", file=sys.stderr)
            return EXIT_FETCH

    snapshot = Snapshot(
        url=args.url or f"{args.serve} (served locally)",
        scraped_at=state.now_utc(),
        products=products,
        pages=pages,
    )

    try:
        previous = state.load(args.state)
    except state.StateError as exc:
        print(f"watch.py: {exc}", file=sys.stderr)
        return EXIT_USAGE

    changes = compare(previous, snapshot)
    summary = report.summarise(snapshot, previous, changes, config.name)
    if notes:
        summary += "\n" + "\n".join(f"note: {n}" for n in notes) + "\n"

    out = Path(args.out)
    rows = report.build_rows(snapshot, previous, changes)
    csv_path = report.write_csv(out / "products.csv", rows)
    xlsx_path = report.write_xlsx(out / "products.xlsx", rows, changes, summary)
    txt_path = report.write_text(out / "changes.txt", summary)

    if args.report:
        print(summary, end="")
    log(f"wrote {csv_path}, {xlsx_path}, {txt_path}")

    if args.no_state:
        log(f"--no-state: {args.state} left at the previous run")
    else:
        state.save(args.state, snapshot)
        log(f"state saved to {args.state}")

    if args.fail_on_review and snapshot.review_count:
        return EXIT_REVIEW
    if args.fail_on_change and changes:
        return EXIT_CHANGED
    return EXIT_OK
