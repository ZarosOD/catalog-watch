"""The run-to-run comparison, on snapshots built in memory."""

from __future__ import annotations

from decimal import Decimal

from catalog_watch.diff import compare
from catalog_watch.models import (
    DELISTED,
    FIRST_READ,
    IN_STOCK,
    NEW,
    OUT_OF_STOCK,
    UNREADABLE,
    Product,
    Snapshot,
)


def snapshot(*products: Product, at="2026-01-01T06:00:00+00:00") -> Snapshot:
    return Snapshot(url="http://example.test/", scraped_at=at, products=list(products), pages=1)


def product(sku="A-1", name="Thing", price="10.00", availability=IN_STOCK, **kw):
    return Product(
        sku=sku,
        name=name,
        price=None if price is None else Decimal(price),
        currency="USD",
        availability=availability,
        **kw,
    )


class TestFirstRun:
    def test_no_previous_run_is_a_baseline_not_thirty_new_products(self):
        assert compare(None, snapshot(product(), product(sku="A-2"))) == []


class TestUnchanged:
    def test_identical_snapshots_produce_nothing(self):
        before = snapshot(product(), product(sku="A-2", price="20.00"))
        after = snapshot(product(), product(sku="A-2", price="20.00"))
        assert compare(before, after) == []

    def test_a_standing_review_flag_is_not_a_change(self):
        # Unreadable on both runs: worth reporting as a flag, but nothing moved.
        flagged = product(price=None, issues=["price: no number in 'POA'"])
        assert compare(snapshot(flagged), snapshot(flagged)) == []


class TestPrice:
    def test_a_cut_reports_the_delta_and_the_percentage(self):
        [change] = compare(
            snapshot(product(price="48.00")), snapshot(product(price="41.50"))
        )
        assert change.kind == "price"
        assert change.before == "48.00"
        assert change.after == "41.50"
        assert change.note == "-6.50 USD (-13.5%)"

    def test_a_rise_is_signed(self):
        [change] = compare(
            snapshot(product(price="87.40")), snapshot(product(price="94.80"))
        )
        assert change.note.startswith("+7.40 USD (+8.5%)")

    def test_a_price_of_zero_before_does_not_divide_by_zero(self):
        [change] = compare(
            snapshot(product(price="0.00")), snapshot(product(price="5.00"))
        )
        assert change.note == "+5.00 USD"


class TestAvailabilityAndName:
    def test_going_out_of_stock(self):
        [change] = compare(
            snapshot(product()), snapshot(product(availability=OUT_OF_STOCK))
        )
        assert change.kind == "availability"
        assert (change.before, change.after) == (IN_STOCK, OUT_OF_STOCK)

    def test_a_rename_is_reported(self):
        [change] = compare(snapshot(product()), snapshot(product(name="Thing v2")))
        assert change.kind == "name"
        assert change.after == "Thing v2"


class TestArrivalsAndDepartures:
    def test_a_new_sku(self):
        [change] = compare(snapshot(product()), snapshot(product(), product(sku="A-9")))
        assert change.kind == NEW
        assert change.sku == "A-9"

    def test_a_missing_sku_is_delisted_with_its_last_known_price(self):
        [change] = compare(snapshot(product(), product(sku="A-9")), snapshot(product()))
        assert change.kind == DELISTED
        assert change.sku == "A-9"
        assert change.before == "10.00"


class TestUnreadableIsNeverAPriceMove:
    def test_a_price_that_stops_parsing_is_flagged_not_reported_as_a_change(self):
        before = snapshot(product(price="48.00"))
        after = snapshot(product(price=None, issues=["price: no number in 'POA'"]))
        [change] = compare(before, after)
        assert change.kind == UNREADABLE
        assert change.after is None
        assert "could not be read" in change.note

    def test_becoming_readable_again_is_its_own_kind(self):
        before = snapshot(product(price=None))
        after = snapshot(product(price="48.00"))
        [change] = compare(before, after)
        assert change.kind == FIRST_READ
        assert change.after == "48.00"


class TestOrdering:
    def test_price_moves_come_before_arrivals_and_departures(self):
        before = snapshot(product(price="10.00"), product(sku="A-2"))
        after = snapshot(product(price="9.00"), product(sku="A-3"))
        kinds = [c.kind for c in compare(before, after)]
        assert kinds == ["price", NEW, DELISTED]
