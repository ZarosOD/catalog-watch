"""Two snapshots in, a list of changes out. Pure, so it is all unit-tested.

The distinction that matters here: a field we *could not read* this run is
reported as ``unreadable``, never as a change in value. A price that goes from
48.00 to "we could not parse it" is not a price cut, and a client who gets told
it is stops trusting the report.
"""

from __future__ import annotations

from decimal import Decimal

from .models import (
    DELISTED,
    FIRST_READ,
    NEW,
    TRACKED_FIELDS,
    UNREADABLE,
    Change,
    Product,
    Snapshot,
)


def _format(field: str, value) -> str:
    if value is None:
        return "-"
    if field == "price":
        return f"{value:.2f}"
    return str(value)


def _price_note(before: Decimal, after: Decimal, currency: str | None) -> str:
    delta = after - before
    sign = "+" if delta > 0 else ""
    unit = f" {currency}" if currency else ""
    if before:
        pct = (delta / before) * 100
        return f"{sign}{delta:.2f}{unit} ({sign}{pct:.1f}%)"
    return f"{sign}{delta:.2f}{unit}"


def compare_products(before: Product, after: Product) -> list[Change]:
    changes: list[Change] = []
    for field in TRACKED_FIELDS:
        old = getattr(before, field)
        new = getattr(after, field)
        if old == new:
            continue

        name = after.name or before.name
        if new is None:
            changes.append(
                Change(
                    kind=UNREADABLE,
                    sku=after.sku,
                    name=name,
                    before=_format(field, old),
                    after=None,
                    note=f"{field} could not be read this run; last known value kept out of the report",
                )
            )
        elif old is None:
            changes.append(
                Change(
                    kind=FIRST_READ,
                    sku=after.sku,
                    name=name,
                    before=None,
                    after=_format(field, new),
                    note=f"{field} was unreadable last run and is readable now",
                )
            )
        else:
            note = ""
            if field == "price":
                note = _price_note(old, new, after.currency or before.currency)
            changes.append(
                Change(
                    kind=field,
                    sku=after.sku,
                    name=name,
                    before=_format(field, old),
                    after=_format(field, new),
                    note=note,
                )
            )
    return changes


def compare(before: Snapshot | None, after: Snapshot) -> list[Change]:
    """Changes from ``before`` to ``after``.

    ``before`` is None on the very first run: there is nothing to compare
    against, so the result is empty and the caller reports a baseline instead
    of announcing every product as new.
    """
    if before is None:
        return []

    old_by_sku = before.by_sku()
    new_by_sku = after.by_sku()
    changes: list[Change] = []

    for sku, product in new_by_sku.items():
        if sku not in old_by_sku:
            price = _format("price", product.price)
            currency = f" {product.currency}" if product.currency else ""
            changes.append(
                Change(
                    kind=NEW,
                    sku=sku,
                    name=product.name,
                    after=f"{price}{currency}".strip(),
                    note="new listing",
                )
            )
        else:
            changes.extend(compare_products(old_by_sku[sku], product))

    for sku, product in old_by_sku.items():
        if sku not in new_by_sku:
            changes.append(
                Change(
                    kind=DELISTED,
                    sku=sku,
                    name=product.name,
                    before=_format("price", product.price),
                    note="no longer listed",
                )
            )

    changes.sort(key=lambda c: c.sort_key)
    return changes
