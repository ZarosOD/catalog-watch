"""The state file. This is what makes the diff real rather than simulated, so
the round trip is worth testing on its own."""

from __future__ import annotations

from decimal import Decimal

import pytest

from catalog_watch import state
from catalog_watch.models import IN_STOCK, Product, Snapshot


def sample() -> Snapshot:
    return Snapshot(
        url="http://example.test/",
        scraped_at="2026-01-01T06:00:00+00:00",
        pages=2,
        products=[
            Product(
                sku="A-1",
                name="Thing",
                price=Decimal("48.00"),
                currency="USD",
                availability=IN_STOCK,
                url="http://example.test/p/A-1",
            ),
            Product(sku="A-2", name="Other", issues=["price: no number in 'POA'"]),
        ],
    )


def test_missing_file_is_a_first_run_not_an_error(tmp_path):
    assert state.load(tmp_path / "nope.json") is None


def test_round_trip_preserves_every_field(tmp_path):
    path = tmp_path / "state.json"
    state.save(path, sample())
    loaded = state.load(path)
    assert loaded.to_json() == sample().to_json()
    assert loaded.products[0].price == Decimal("48.00")
    assert loaded.products[1].price is None
    assert loaded.products[1].issues == ["price: no number in 'POA'"]


def test_prices_survive_as_decimals_not_floats(tmp_path):
    path = tmp_path / "state.json"
    snap = sample()
    snap.products[0].price = Decimal("0.10")
    state.save(path, snap)
    assert state.load(path).products[0].price == Decimal("0.10")


def test_save_creates_the_parent_directory(tmp_path):
    path = tmp_path / "deep" / "state.json"
    state.save(path, sample())
    assert path.exists()


def test_save_leaves_no_temp_file_behind(tmp_path):
    state.save(tmp_path / "state.json", sample())
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_corrupt_state_says_what_to_do(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(state.StateError, match="Delete it"):
        state.load(path)


def test_a_future_version_is_refused_rather_than_misread(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"version": 2, "products": []}', encoding="utf-8")
    with pytest.raises(state.StateError, match="different version"):
        state.load(path)
