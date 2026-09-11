"""HTML in, products out. No network, no disk — so nearly every test in this
repo runs against a string.

The rule the whole file is built around: a field that cannot be read is left
empty and flagged. It is never inferred from a neighbouring field, carried over
from the previous run, or defaulted to something plausible.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .models import Product
from .site import SiteConfig

CURRENCY_SYMBOLS = {
    "$": "USD",
    "£": "GBP",
    "€": "EUR",
    "¥": "JPY",
    "₹": "INR",
}

# 1,299.00 / 48.00 / 1299 — thousands separators optional, decimals optional.
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_ISO_CODE = re.compile(r"\b([A-Z]{3})\b")


def _soup(html: str) -> BeautifulSoup:
    # html.parser is stdlib, so there is no lxml wheel to install and no C
    # toolchain needed on the machine running this.
    return BeautifulSoup(html, "html.parser")


def parse_money(text: str) -> tuple[Decimal | None, str | None, str | None]:
    """Return ``(amount, currency, issue)``.

    ``issue`` is non-None when the text could not be read as a single price.
    Two prices in one cell ("$60.00 $48.00") is a mis-aimed selector, so it is
    reported rather than resolved by picking one.
    """
    raw = " ".join(text.split())
    if not raw:
        return None, None, "price: empty"

    currency = None
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in raw:
            currency = code
            break
    if currency is None:
        match = _ISO_CODE.search(raw)
        if match:
            currency = match.group(1)

    numbers = _NUMBER.findall(raw)
    if not numbers:
        return None, currency, f"price: no number in {raw!r}"
    if len({n.replace(",", "") for n in numbers}) > 1:
        return None, currency, f"price: more than one number in {raw!r}"

    try:
        amount = Decimal(numbers[0].replace(",", ""))
    except InvalidOperation:
        return None, currency, f"price: cannot read {numbers[0]!r} as a number"
    return amount, currency, None


def _read_field(card, spec, base_url: str, config: SiteConfig):
    """Return ``(value, currency, issue, found)`` for one field of one card.

    ``found`` separates "this card has no such element" from "the element is
    there and its contents make no sense". The second is always worth
    reporting; the first is only worth reporting for a required field.
    """
    element = card.select_one(spec.selector)
    if element is None:
        return None, None, "not on the card", False

    if spec.attr:
        raw = element.get(spec.attr)
        if raw is None:
            return None, None, f"no {spec.attr!r} attribute", True
        raw = raw if isinstance(raw, str) else " ".join(raw)
    else:
        raw = element.get_text(" ", strip=True)

    raw = " ".join(raw.split())
    if not raw:
        return None, None, "empty", True

    if spec.parse == "money":
        amount, currency, issue = parse_money(raw)
        return amount, currency, (issue.split(": ", 1)[1] if issue else None), True
    if spec.parse == "availability":
        value = config.normalise_availability(raw)
        if value is None:
            return None, None, f"unrecognised value {raw!r}", True
        return value, None, None, True
    if spec.parse == "url":
        return urljoin(base_url, raw), None, None, True
    return raw, None, None, True


def parse_products(html: str, config: SiteConfig, base_url: str = "") -> list[Product]:
    """Every product card on one page, in page order.

    A card with no readable sku cannot be matched against the previous run, so
    it is skipped and counted by :func:`count_unidentified` rather than given a
    made-up key.
    """
    soup = _soup(html)
    products: list[Product] = []

    for card in soup.select(config.product_selector):
        sku_value, _, sku_issue, _ = _read_field(
            card, config.fields["sku"], base_url, config
        )
        if sku_issue or not sku_value:
            continue

        product = Product(sku=str(sku_value))
        for name, spec in config.fields.items():
            if name == "sku":
                continue
            value, currency, issue, found = _read_field(card, spec, base_url, config)
            if issue and (found or name in config.required):
                product.flag(f"{name}: {issue}")
            if name == "price":
                product.price = value
                if currency:
                    product.currency = currency
            else:
                setattr(product, name, value)

        products.append(product)

    return products


def count_unidentified(html: str, config: SiteConfig) -> int:
    """Product cards on the page whose sku could not be read.

    Reported by the CLI so that cards dropped for want of a key are visible
    rather than silently absent from the count.
    """
    soup = _soup(html)
    missing = 0
    for card in soup.select(config.product_selector):
        value, _, issue, _ = _read_field(card, config.fields["sku"], "", config)
        if issue or not value:
            missing += 1
    return missing


def find_next_page(html: str, config: SiteConfig, base_url: str) -> str | None:
    """The absolute URL of the next page, or None if this is the last one."""
    if not config.next_selector:
        return None
    soup = _soup(html)
    link = soup.select_one(config.next_selector)
    if link is None:
        return None
    href = link.get("href")
    if not href:
        return None
    return urljoin(base_url, href)
