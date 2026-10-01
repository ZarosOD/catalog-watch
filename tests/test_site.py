"""Site profiles fail at load time, with a message that says what to fix —
not forty pages into a crawl."""

from __future__ import annotations

import dataclasses

import pytest

from catalog_watch.models import Product
from catalog_watch.site import KNOWN_FIELDS, SiteConfig, SiteConfigError


def profile(**overrides):
    data = {
        "name": "test",
        "product": {"selector": ".p"},
        "fields": {"sku": {"selector": ".sku"}},
    }
    data.update(overrides)
    return data


def test_the_bundled_fixture_profile_loads(repo):
    config = SiteConfig.load(repo / "sites" / "fixture.json")
    assert config.product_selector == "article.product"
    assert set(config.required) == {"sku", "name", "price"}
    assert config.next_selector == "a.next"


def test_a_missing_file_says_where_it_looked(tmp_path):
    with pytest.raises(SiteConfigError, match="no site profile at"):
        SiteConfig.load(tmp_path / "nope.json")


def test_invalid_json_says_so(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(SiteConfigError, match="not valid JSON"):
        SiteConfig.load(path)


def test_no_product_selector():
    with pytest.raises(SiteConfigError, match="product.selector"):
        SiteConfig.from_json({"fields": {"sku": {"selector": ".s"}}})


def test_no_sku_field_explains_why_it_is_needed():
    with pytest.raises(SiteConfigError, match="matched between runs by sku"):
        SiteConfig.from_json(profile(fields={"name": {"selector": ".n"}}))


def test_a_typo_in_a_field_name_is_caught_at_load():
    with pytest.raises(SiteConfigError, match="unknown field"):
        SiteConfig.from_json(
            profile(fields={"sku": {"selector": ".s"}, "pirce": {"selector": ".p"}})
        )


def test_an_unknown_parser_lists_the_valid_ones():
    with pytest.raises(SiteConfigError, match="money"):
        SiteConfig.from_json(
            profile(fields={"sku": {"selector": ".s", "parse": "magic"}})
        )


def test_a_field_with_no_selector():
    with pytest.raises(SiteConfigError, match="missing 'selector'"):
        SiteConfig.from_json(profile(fields={"sku": {"attr": "data-sku"}}))


def test_required_must_name_defined_fields():
    with pytest.raises(SiteConfigError, match="not defined"):
        SiteConfig.from_json(profile(required=["sku", "price"]))


def test_a_profile_can_declare_category_and_description():
    """The load-time gate, not a column: `KNOWN_FIELDS` is enforced hard, so
    before THE-452 these two names were a SiteConfigError and a profile could
    not opt in."""
    config = SiteConfig.from_json(
        profile(
            fields={
                "sku": {"selector": ".sku"},
                "category": {"selector": ".cat"},
                "description": {"selector": ".blurb"},
            }
        )
    )
    assert config.fields["category"].selector == ".cat"
    assert config.fields["description"].selector == ".blurb"
    # Both default to the plain-text parser, same as `name`.
    assert config.fields["category"].parse == "text"
    assert config.fields["description"].parse == "text"


def test_either_new_field_can_be_required():
    config = SiteConfig.from_json(
        profile(
            fields={"sku": {"selector": ".sku"}, "category": {"selector": ".cat"}},
            required=["sku", "category"],
        )
    )
    assert set(config.required) == {"sku", "category"}


def test_the_unknown_field_message_lists_the_two_new_names():
    """The message is the only place a profile author learns what they may
    write, so it is asserted on by content and not just by shape."""
    with pytest.raises(SiteConfigError) as caught:
        SiteConfig.from_json(
            profile(fields={"sku": {"selector": ".s"}, "catagory": {"selector": ".c"}})
        )
    message = str(caught.value)
    assert "category" in message
    assert "description" in message


def test_the_unknown_field_message_does_not_call_the_list_tracked():
    """`description` is collected and never diffed, so a message calling this
    list the tracked set would be a false sentence — models.TRACKED_FIELDS is
    the watched subset. tests/test_diff.py pins the other half of this."""
    with pytest.raises(SiteConfigError) as caught:
        SiteConfig.from_json(
            profile(fields={"sku": {"selector": ".s"}, "pirce": {"selector": ".p"}})
        )
    message = str(caught.value)
    assert "this tool collects" in message
    assert "tracks" not in message


def test_every_declarable_field_is_a_field_a_product_has():
    """The coupling that made THE-452 a four-file change rather than a
    one-line one: `KNOWN_FIELDS` is the profile's vocabulary and `Product` is
    where the scraper puts it (`scrape.parse_products` does a bare `setattr`),
    so a name in one and not the other is an AttributeError 40 pages into a
    crawl, or a column nothing can ever fill.

    `currency` is the one Product field a profile may not name, and that is
    deliberate: it is read off the price text by `parse_money`, not selected.
    Naming it here means a future field cannot join that exemption silently.
    """
    product_fields = {f.name for f in dataclasses.fields(Product)} - {"issues"}
    assert set(KNOWN_FIELDS) <= product_fields
    assert product_fields - set(KNOWN_FIELDS) == {"currency"}


def test_unrecognised_availability_is_none_not_a_guess():
    config = SiteConfig.from_json(profile())
    assert config.normalise_availability("Ask in store") is None
    assert config.normalise_availability("  IN   STOCK ") == "in_stock"
