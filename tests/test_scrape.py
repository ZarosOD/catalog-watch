"""Parsing rules, on HTML strings. No network, no fixtures on disk."""

from __future__ import annotations

from decimal import Decimal

import pytest

from catalog_watch.models import BACKORDER, IN_STOCK, OUT_OF_STOCK, PREORDER
from catalog_watch.scrape import (
    count_unidentified,
    find_next_page,
    parse_money,
    parse_products,
)

from helpers import card, make_config, make_config_with_extras, page


@pytest.fixture
def config():
    return make_config()


class TestParseMoney:
    @pytest.mark.parametrize(
        "text,amount,currency",
        [
            ("$48.00", Decimal("48.00"), "USD"),
            ("48.00 USD", Decimal("48.00"), "USD"),
            ("USD 48", Decimal("48"), "USD"),
            ("£1,299.00", Decimal("1299.00"), "GBP"),
            ("€9.99", Decimal("9.99"), "EUR"),
            ("  $ 1,024.50  ", Decimal("1024.50"), "USD"),
            ("12.75", Decimal("12.75"), None),
        ],
    )
    def test_reads_a_price(self, text, amount, currency):
        value, found_currency, issue = parse_money(text)
        assert issue is None
        assert value == amount
        assert found_currency == currency

    @pytest.mark.parametrize(
        "text", ["Call for pricing", "POA", "Contact us", "—", ""]
    )
    def test_no_number_is_flagged_not_guessed(self, text):
        value, _, issue = parse_money(text)
        assert value is None
        assert issue is not None

    def test_two_prices_in_one_cell_is_ambiguous(self):
        # A "was $60.00, now $48.00" cell means the selector is pointing at the
        # wrong element. Picking one would be a guess.
        value, _, issue = parse_money("$60.00 $48.00")
        assert value is None
        assert "more than one number" in issue

    def test_the_same_number_twice_is_not_ambiguous(self):
        value, _, issue = parse_money("$48.00 (48.00 inc. tax)")
        assert issue is None
        assert value == Decimal("48.00")


class TestParseProducts:
    def test_reads_every_field(self, config):
        products = parse_products(
            page(card()), config, "http://example.test/catalogue/"
        )
        assert len(products) == 1
        product = products[0]
        assert product.sku == "A-1"
        assert product.name == "Thing"
        assert product.price == Decimal("10.00")
        assert product.currency == "USD"
        assert product.availability == IN_STOCK
        assert product.url == "http://example.test/catalogue/p/A-1.html"
        assert not product.needs_review

    def test_unreadable_price_is_empty_and_flagged(self, config):
        [product] = parse_products(page(card(price="Call for pricing")), config)
        assert product.price is None
        assert product.needs_review
        assert product.issues == ["price: no number in 'Call for pricing'"]

    def test_missing_required_element_is_flagged(self, config):
        [product] = parse_products(page(card(price=None)), config)
        assert product.price is None
        assert product.issues == ["price: not on the card"]

    def test_missing_optional_element_is_not_flagged(self, config):
        [product] = parse_products(page(card(link=None)), config)
        assert product.url is None
        assert not product.needs_review

    def test_present_but_unreadable_optional_field_is_flagged(self, config):
        [product] = parse_products(page(card(stock="Ask in store")), config)
        assert product.availability is None
        assert product.issues == ["availability: unrecognised value 'Ask in store'"]

    def test_a_card_with_no_sku_is_skipped_and_counted(self, config):
        html = page(card(sku="A-1"), card(sku=None))
        products = parse_products(html, config)
        assert [p.sku for p in products] == ["A-1"]
        assert count_unidentified(html, config) == 1

    @pytest.mark.parametrize(
        "printed,expected",
        [
            ("In stock", IN_STOCK),
            ("in  stock", IN_STOCK),
            ("Out of stock", OUT_OF_STOCK),
            ("Sold out", OUT_OF_STOCK),
            ("Back-order", BACKORDER),
            ("Pre-order", PREORDER),
        ],
    )
    def test_availability_normalisation(self, config, printed, expected):
        [product] = parse_products(page(card(stock=printed)), config)
        assert product.availability == expected

    def test_profile_can_extend_the_availability_map(self):
        config = make_config(availability_map={"ships in 48h": "in_stock"})
        [product] = parse_products(page(card(stock="Ships in 48h")), config)
        assert product.availability == IN_STOCK

    def test_page_order_is_preserved(self, config):
        html = page(card(sku="A-1"), card(sku="A-2"), card(sku="A-3"))
        assert [p.sku for p in parse_products(html, config)] == ["A-1", "A-2", "A-3"]

    def test_empty_page_is_not_an_error(self, config):
        assert parse_products("<html><body></body></html>", config) == []


class TestCategoryAndDescription:
    """THE-452's scope listed `scrape.py` as an edit site and it was not one:
    `parse_products` loops the profile's declared fields and ends in a bare
    `setattr(product, name, value)`, so the plumbing was already generic once
    `KNOWN_FIELDS` and `Product` knew the names. These tests exist because "no
    change needed" is a claim, and an unasserted one is a guess.
    """

    @pytest.fixture
    def extras(self):
        return make_config_with_extras()

    def test_both_fields_are_read_off_the_card(self, extras):
        html = page(
            card(category="Rope & Chain", description="Twelve millimetre braided line.")
        )
        [product] = parse_products(html, extras)
        assert product.category == "Rope & Chain"
        assert product.description == "Twelve millimetre braided line."
        assert product.issues == []

    def test_a_missing_optional_element_is_none_and_not_flagged(self, extras):
        """"Not on the card" for a field nobody called required is a fact
        about the storefront, not a defect — the treatment `url` already gets.
        The value stays None and nothing is defaulted."""
        [product] = parse_products(page(card()), extras)
        assert product.category is None
        assert product.description is None
        assert product.issues == []

    def test_an_empty_element_is_none_with_an_issues_line(self, extras):
        """The element is on the card and says nothing. That is worth
        reporting, and it is still not worth guessing at."""
        [product] = parse_products(page(card(category="", description="")), extras)
        assert product.category is None
        assert product.description is None
        assert "category: empty" in product.issues
        assert "description: empty" in product.issues
        assert product.needs_review

    def test_a_required_category_missing_from_the_card_is_flagged(self):
        config = make_config_with_extras(required=["sku", "category"])
        [product] = parse_products(page(card()), config)
        assert product.category is None
        assert "category: not on the card" in product.issues

    def test_neither_field_is_filled_in_from_the_other(self, extras):
        """Product's docstring promises a field that could not be read is
        never filled from a default, from the previous run, or from another
        field. Two adjacent text fields are where that breaks first."""
        [product] = parse_products(page(card(category="Rope & Chain")), extras)
        assert product.category == "Rope & Chain"
        assert product.description is None
        [other] = parse_products(page(card(description="Braided line.")), extras)
        assert other.description == "Braided line."
        assert other.category is None


class TestPagination:
    def test_finds_the_next_page(self, config):
        html = page(card(), next_href="page2.html")
        assert (
            find_next_page(html, config, "http://example.test/catalogue/")
            == "http://example.test/catalogue/page2.html"
        )

    def test_last_page_has_no_next(self, config):
        assert find_next_page(page(card()), config, "http://example.test/") is None

    def test_no_pagination_configured(self):
        config = make_config(pagination={})
        html = page(card(), next_href="page2.html")
        assert find_next_page(html, config, "http://example.test/") is None
