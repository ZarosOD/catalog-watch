"""CSV shape, XLSX contents, and the wording of the text summary."""

from __future__ import annotations

import csv
from decimal import Decimal

from catalog_watch import report
from catalog_watch.diff import compare
from catalog_watch.models import IN_STOCK, OUT_OF_STOCK, Product, Snapshot


def snapshot(*products: Product, at="2026-01-02T06:00:00+00:00") -> Snapshot:
    return Snapshot(url="http://example.test/", scraped_at=at, products=list(products), pages=2)


def product(sku="A-1", name="Thing", price="10.00", availability=IN_STOCK, **kw):
    return Product(
        sku=sku,
        name=name,
        price=None if price is None else Decimal(price),
        currency="USD",
        availability=availability,
        url=f"http://example.test/p/{sku}",
        **kw,
    )


def build(before: Snapshot | None, after: Snapshot):
    changes = compare(before, after)
    rows = report.build_rows(after, before, changes)
    return changes, rows


class TestCsv:
    def test_header_and_one_row_per_product(self, tmp_path):
        _, rows = build(None, snapshot(product(), product(sku="A-2")))
        path = report.write_csv(tmp_path / "products.csv", rows)
        with path.open(encoding="utf-8") as handle:
            read = list(csv.DictReader(handle))
        assert list(read[0]) == report.COLUMNS
        assert [r["sku"] for r in read] == ["A-1", "A-2"]
        assert read[0]["status"] == "listed"

    def test_a_delisted_product_still_gets_a_row(self, tmp_path):
        before = snapshot(product(), product(sku="A-2"))
        after = snapshot(product())
        _, rows = build(before, after)
        path = report.write_csv(tmp_path / "products.csv", rows)
        with path.open(encoding="utf-8") as handle:
            read = list(csv.DictReader(handle))
        gone = [r for r in read if r["sku"] == "A-2"]
        assert len(gone) == 1
        assert gone[0]["status"] == "delisted"
        assert gone[0]["change"] == "delisted"

    def test_an_unreadable_price_is_an_empty_cell_not_a_zero(self, tmp_path):
        _, rows = build(
            None, snapshot(product(price=None, issues=["price: no number in 'POA'"]))
        )
        path = report.write_csv(tmp_path / "products.csv", rows)
        with path.open(encoding="utf-8") as handle:
            [row] = list(csv.DictReader(handle))
        assert row["price"] == ""
        assert row["needs_review"] == "yes"
        assert "POA" in row["issues"]

    def test_the_change_columns_carry_the_movement(self, tmp_path):
        before = snapshot(product(price="48.00"))
        after = snapshot(product(price="41.50"))
        _, rows = build(before, after)
        path = report.write_csv(tmp_path / "products.csv", rows)
        with path.open(encoding="utf-8") as handle:
            [row] = list(csv.DictReader(handle))
        assert row["change"] == "price cut"
        assert "48.00 -> 41.50" in row["change_detail"]


class TestXlsx:
    def test_three_sheets_with_changes_first(self, tmp_path):
        from openpyxl import load_workbook

        before = snapshot(product(price="48.00"))
        after = snapshot(product(price="41.50"), product(sku="A-2"))
        changes, rows = build(before, after)
        path = report.write_xlsx(
            tmp_path / "products.xlsx", rows, changes, "summary text"
        )
        book = load_workbook(path)
        assert book.sheetnames == ["Changes", "Catalogue", "Run"]
        assert [c.value for c in book["Changes"][1]] == [
            "kind",
            "sku",
            "name",
            "before",
            "after",
            "detail",
        ]
        assert book["Changes"].cell(row=2, column=1).value == "price cut"
        assert book["Catalogue"].max_row == len(rows) + 1

    def test_no_changes_says_so_rather_than_leaving_a_blank_sheet(self, tmp_path):
        from openpyxl import load_workbook

        snap = snapshot(product())
        changes, rows = build(snapshot(product()), snap)
        path = report.write_xlsx(tmp_path / "p.xlsx", rows, changes, "summary")
        book = load_workbook(path)
        assert "no changes" in book["Changes"].cell(row=2, column=1).value


class TestSummary:
    def test_first_run_says_baseline(self):
        text = report.summarise(snapshot(product()), None, [], "Test Shop")
        assert "First run" in text
        assert "baseline" in text

    def test_no_changes_says_no_changes(self):
        snap = snapshot(product())
        text = report.summarise(snap, snapshot(product()), [], "Test Shop")
        assert "No changes since the previous run." in text

    def test_a_change_names_the_product_and_the_movement(self):
        before = snapshot(product(price="48.00"))
        after = snapshot(product(price="41.50"))
        changes = compare(before, after)
        text = report.summarise(after, before, changes, "Test Shop")
        assert "1 change since the previous run" in text
        assert "price cut" in text
        assert "A-1" in text
        assert "48.00 -> 41.50" in text
        assert "-13.5%" in text

    def test_availability_reads_as_words_not_identifiers(self):
        before = snapshot(product())
        after = snapshot(product(availability=OUT_OF_STOCK))
        text = report.summarise(after, before, compare(before, after), "Test Shop")
        assert "in stock -> out of stock" in text

    def test_new_and_delisted_do_not_print_a_stray_dash(self):
        before = snapshot(product(sku="A-1"))
        after = snapshot(product(sku="A-2"))
        text = report.summarise(after, before, compare(before, after), "Test Shop")
        assert "-> 10.00 USD" in text
        assert "10.00 ->" in text
        assert "- -> " not in text

    def test_flagged_products_are_listed_with_their_reason(self):
        snap = snapshot(product(price=None, issues=["price: no number in 'POA'"]))
        text = report.summarise(snap, None, [], "Test Shop")
        assert "1 product needing review" in text
        assert "POA" in text

    def test_counts_read_clean_and_needing_review(self):
        snap = snapshot(product(), product(sku="A-2", issues=["price: missing"]))
        text = report.summarise(snap, None, [], "Test Shop")
        assert "2 products on 2 pages · 1 read clean · 1 needing review" in text
