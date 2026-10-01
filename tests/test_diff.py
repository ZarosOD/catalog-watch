"""The run-to-run comparison, on snapshots built in memory."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

from catalog_watch.diff import compare
from catalog_watch.models import (
    DELISTED,
    FIRST_READ,
    IN_STOCK,
    KIND_ORDER,
    NEW,
    OUT_OF_STOCK,
    TRACKED_FIELDS,
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

    def test_a_category_move_sorts_with_the_other_value_moves(self):
        """`Change.sort_key` ranks an unlisted kind *after* everything, so a
        field added to TRACKED_FIELDS and not to KIND_ORDER gets printed below
        `readable` instead of beside the price and stock moves. Silent, and
        only this ordering can see it."""
        before = snapshot(product(category="Rope"), product(sku="A-2"))
        after = snapshot(product(category="Deck"), product(sku="A-3"))
        kinds = [c.kind for c in compare(before, after)]
        assert kinds == ["category", NEW, DELISTED]

    def test_every_tracked_field_has_a_rank_of_its_own(self):
        """The structural half: KIND_ORDER is derived from TRACKED_FIELDS, and
        this fails if someone re-literalises it and forgets an entry."""
        for field in TRACKED_FIELDS:
            assert field in KIND_ORDER, field
        for kind in (NEW, DELISTED, UNREADABLE, FIRST_READ):
            assert KIND_ORDER.index(kind) > max(
                KIND_ORDER.index(f) for f in TRACKED_FIELDS
            )


class TestCategoryIsWatchedAndDescriptionIsNot:
    """THE-452's judgement call, pinned in both directions.

    A product moving category is a catalogue event a client wants told. A
    description is prose vendors re-word constantly, so diffing it would make
    every re-word a change row and bury the price cuts the report exists to
    carry — and each row would drag its before and after text through the
    fixed-width summary that the scheduled job emails.
    """

    def test_a_category_move_is_reported(self):
        [change] = compare(
            snapshot(product(category="Rope & Chain")),
            snapshot(product(category="Deck Hardware")),
        )
        assert change.kind == "category"
        assert (change.before, change.after) == ("Rope & Chain", "Deck Hardware")

    def test_a_rewritten_description_is_not_a_change(self):
        assert (
            compare(
                snapshot(product(description="Twelve millimetre braided line.")),
                snapshot(product(description="Braided 12mm line, sold by the metre.")),
            )
            == []
        )

    def test_a_description_that_stops_reading_is_not_a_change_either(self):
        """The mirror of the test above. If `description` were tracked, a
        selector that broke for one morning would emit an `unreadable` row per
        product — the loudest possible way to report nothing."""
        before = snapshot(product(description="Twelve millimetre braided line."))
        after = snapshot(product(description=None))
        assert compare(before, after) == []

    def test_description_is_absent_from_tracked_fields_on_purpose(self):
        """Declared, not left to be noticed: the three tests above all pass if
        `description` is simply never set, so this one names the cause."""
        assert "description" in {f.name for f in dataclasses.fields(Product)}
        assert "description" not in TRACKED_FIELDS
        assert "category" in TRACKED_FIELDS

    def test_a_category_that_stops_reading_is_unreadable_not_a_move(self):
        before = snapshot(product(category="Rope & Chain"))
        after = snapshot(product(category=None, issues=["category: not on the card"]))
        [change] = compare(before, after)
        assert change.kind == UNREADABLE
        assert change.before == "Rope & Chain"
        assert change.after is None
        assert "category could not be read this run" in change.note


class TestAStateFileWrittenBeforeTheseFieldsExisted:
    """`category` and `description` were added without bumping the state
    version, so a client's baseline survives the upgrade. The first run after
    it sees None -> a value, which is FIRST_READ — and the note it prints has
    to be true of a cause nobody measured."""

    def test_an_old_snapshot_round_trips_without_the_new_keys(self):
        old = {
            "version": 1,
            "url": "http://example.test/",
            "scraped_at": "2026-01-01T06:00:00+00:00",
            "pages": 1,
            "products": [
                {
                    "sku": "A-1",
                    "name": "Thing",
                    "price": "10.00",
                    "currency": "USD",
                    "availability": IN_STOCK,
                    "url": "http://example.test/p/A-1",
                    "issues": [],
                }
            ],
        }
        [restored] = Snapshot.from_json(old).products
        assert restored.category is None
        assert restored.description is None

    def test_the_first_read_note_does_not_claim_the_field_was_unreadable(self):
        before = snapshot(product(category=None))
        after = snapshot(product(category="Deck Hardware"))
        [change] = compare(before, after)
        assert change.kind == FIRST_READ
        assert change.after == "Deck Hardware"
        assert change.note == (
            "category had no recorded value last run and is readable now"
        )
        assert "unreadable" not in change.note

    def test_the_wording_changed_for_every_tracked_field_not_just_the_new_one(self):
        """One note string serves all of TRACKED_FIELDS, so the reword is a
        claim about `price` too. Asserted here rather than assumed."""
        [change] = compare(
            snapshot(product(price=None)), snapshot(product(price="48.00"))
        )
        assert change.kind == FIRST_READ
        assert change.note == "price had no recorded value last run and is readable now"
