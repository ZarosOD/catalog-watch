"""Site profiles fail at load time, with a message that says what to fix —
not forty pages into a crawl."""

from __future__ import annotations

import pytest

from catalog_watch.site import SiteConfig, SiteConfigError


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


def test_unrecognised_availability_is_none_not_a_guess():
    config = SiteConfig.from_json(profile())
    assert config.normalise_availability("Ask in store") is None
    assert config.normalise_availability("  IN   STOCK ") == "in_stock"
