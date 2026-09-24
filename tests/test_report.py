"""CSV shape, XLSX contents, and the wording of the text summary."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from decimal import Decimal
from xml.etree import ElementTree

from catalog_watch import report
from catalog_watch.diff import compare
from catalog_watch.models import IN_STOCK, OUT_OF_STOCK, Product, Snapshot
from catalog_watch.serve import FIXTURE_ORIGIN


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

    def test_prices_are_numbers_not_text(self, tmp_path):
        from openpyxl import load_workbook

        before = snapshot(product(price="48.00"))
        after = snapshot(product(price="41.50"))
        changes, rows = build(before, after)
        path = report.write_xlsx(tmp_path / "p.xlsx", rows, changes, "s")
        book = load_workbook(path)

        catalogue = book["Catalogue"]
        price_cell = catalogue.cell(row=2, column=report.COLUMNS.index("price") + 1)
        assert price_cell.value == 41.5
        assert price_cell.number_format == "0.00"

        change_sheet = book["Changes"]
        assert change_sheet.cell(row=2, column=4).value == 48.0
        assert change_sheet.cell(row=2, column=5).value == 41.5

    def test_an_unreadable_price_stays_empty_rather_than_becoming_zero(self, tmp_path):
        from openpyxl import load_workbook

        _, rows = build(None, snapshot(product(price=None, issues=["price: missing"])))
        path = report.write_xlsx(tmp_path / "p.xlsx", rows, [], "s")
        book = load_workbook(path)
        cell = book["Catalogue"].cell(row=2, column=report.COLUMNS.index("price") + 1)
        assert cell.value in (None, "")


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


def with_a_moved_clock(data: bytes) -> bytes:
    """The same workbook as a machine whose clock reads differently wrote it.

    Both clocks move: the zip member stamps and the Office document's own
    `dcterms` timestamps. This exists because writing the file twice inside
    one test proves nothing — both saves land in the same second, so the check
    passes whether or not anything was flattened. Moving the clock by hand is
    what makes the assertion load-bearing.
    """
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            body = source.read(item.filename)
            if item.filename == "docProps/core.xml":
                body = report._TIMESTAMP.sub(rb"\g<1>2031-07-04T11:22:33Z\g<2>", body)
            info = zipfile.ZipInfo(item.filename, date_time=(2031, 7, 4, 11, 22, 32))
            info.compress_type = item.compress_type
            info.external_attr = item.external_attr
            info.create_system = 0
            target.writestr(info, body)
    return out.getvalue()


class TestReproducible:
    """A watcher that runs every morning is read by comparing this morning's
    file to yesterday's, so the bytes have to be decided by the catalogue and
    not by the clock. An .xlsx is a zip of timestamped members and an Office
    document with its own clock; both are flattened in `report._repack`."""

    def _written(self, tmp_path):
        before = snapshot(product(price="48.00"))
        after = snapshot(product(price="41.50"), product(sku="A-2"))
        changes, rows = build(before, after)
        return report.write_xlsx(tmp_path / "products.xlsx", rows, changes, "summary")

    def test_a_run_on_a_different_clock_produces_the_same_bytes(self, tmp_path):
        """The real claim: what the file holds decides its bytes, and when it
        was written does not. Feeding `_repack` a copy with both clocks moved
        has to give back exactly what the tool wrote."""
        written = self._written(tmp_path).read_bytes()
        assert report._repack(with_a_moved_clock(written)) == written

    def test_two_runs_a_day_apart_produce_identical_bytes(self, tmp_path):
        """Two runs over an unchanged catalogue leave one file, so `cmp` can
        stand in for "nothing moved overnight"."""
        before = snapshot(product(price="48.00"))
        after = snapshot(product(price="41.50"))
        changes, rows = build(before, after)
        first = report.write_xlsx(tmp_path / "first.xlsx", rows, changes, "s")
        second = report.write_xlsx(tmp_path / "second.xlsx", rows, changes, "s")
        assert first.read_bytes() == second.read_bytes()

    def test_the_document_clock_is_flattened_not_just_the_zip(self, tmp_path):
        """Two clocks, two fixes. Rewriting only the zip member timestamps
        would leave docProps/core.xml differing every run, and the file would
        still fail `cmp` while looking like it had been handled.

        Measured on openpyxl 3.1.5: `created` honours the workbook property
        and `modified` is refreshed to the save time regardless, so both
        timestamps are checked by name. Asserting the epoch appears
        *somewhere* in core.xml passes on `created` alone while `modified`
        still moves.
        """
        path = self._written(tmp_path)
        with zipfile.ZipFile(path) as book:
            core = book.read("docProps/core.xml").decode("utf-8")
            stamps = dict(re.findall(r"<dcterms:(created|modified)[^>]*>([^<]*)<", core))
            assert stamps == {
                "created": "1980-01-01T00:00:00Z",
                "modified": "1980-01-01T00:00:00Z",
            }
            assert all(
                item.date_time == (1980, 1, 1, 0, 0, 0) for item in book.infolist()
            )

    def test_a_cli_run_leaves_no_wall_clock_in_the_workbook(self, repo, tmp_path):
        """The same claim through the entry point `make run` calls, because a
        repack that the library applies and the CLI path bypasses would pass
        every test above and still ship a moving file.

        This asserts the *container* is flat. What two CLI runs do to each
        other is the next class down, which is the stronger claim and the one
        to read first.
        """
        from catalog_watch.cli import main

        main(
            [
                "--serve",
                str(repo / "fixtures" / "site-day2"),
                "--site",
                str(repo / "sites" / "fixture.json"),
                "--state",
                str(tmp_path / "state.json"),
                "--out",
                str(tmp_path / "out"),
                "--quiet",
                "--report",
            ]
        )
        with zipfile.ZipFile(tmp_path / "out" / "products.xlsx") as book:
            core = book.read("docProps/core.xml").decode("utf-8")
            stamps = dict(re.findall(r"<dcterms:(created|modified)[^>]*>([^<]*)<", core))
            assert set(stamps.values()) == {"1980-01-01T00:00:00Z"}
            assert all(
                item.date_time == (1980, 1, 1, 0, 0, 0) for item in book.infolist()
            )


#: Why the Run sheet is exempt below, spelled out because a bare skip reads
#: like a defect somebody gave up on. `run at <timestamp>` is the line a person
#: checks to know this morning's 06:00 run actually happened — deliberate
#: provenance on a daily watcher's report, kept on purpose. A watcher whose
#: report cannot say when it ran is worse than one whose report fails `cmp`.
#: Everything else in the file is decided by the catalogue, so everything else
#: has to be byte-identical; the exemption is one sheet wide and no wider.
#:
#: Two cells move, not one: `run at` (report.py:283, this run's clock) and
#: `compared against the run at` (report.py:300, the baseline's). A real
#: `make run` writes its own baseline each pass, so both move there even
#: though `_two_runs` below pins the second. Both are provenance and both are
#: confined to this sheet — `test_the_previous_runs_clock_is_confined_to_the_
#: run_sheet` is what holds that second half up.
RUN_SHEET_IS_DELIBERATE_PROVENANCE = """
The Run sheet is the only member allowed to move between two runs, because it
prints two timestamps as visible cells on purpose: this run's clock, and the
clock of the baseline it compared against. If this assertion is failing on
some *other* member, that member has picked up something that is not the
catalogue — find it, do not widen this exemption.
"""

_MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def sheet_members(path) -> dict[str, str]:
    """Map sheet title -> zip member, e.g. ``{"Run": "xl/worksheets/sheet3.xml"}``.

    Resolved through workbook.xml rather than assuming "the Run sheet is
    sheet3.xml", which stops being true the day somebody inserts a sheet — and
    would silently exempt the wrong one.
    """
    def member(target: str) -> str:
        # An OPC target starting with "/" is from the package root; anything
        # else is relative to the part holding the rels, i.e. xl/. openpyxl
        # writes the absolute form, but both are legal and both get read.
        return target.lstrip("/") if target.startswith("/") else "xl/" + target

    with zipfile.ZipFile(path) as book:
        targets = {
            node.get("Id"): member(node.get("Target"))
            for node in ElementTree.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        }
        workbook = ElementTree.fromstring(book.read("xl/workbook.xml"))
    return {
        sheet.get("name"): targets[sheet.get(_REL_NS + "id")]
        for sheet in workbook.iter(_MAIN_NS + "sheet")
    }


class TestTwoRunsOverOneCatalogue:
    """Run the tool twice over the same catalogue on two different days and
    every byte it writes has to be the same, bar the Run sheet.

    This is the claim the whole `_repack` effort is for, asserted end to end
    through `main()` rather than through the library, and it is where the two
    per-run accidents get caught:

      * the **wall clock**, flattened in the container by `_repack` and moved
        by hand here so this cannot pass by two runs landing in one second;
      * the **ephemeral port**, canonicalised in `serve.without_serving_origin`
        — the fixture server binds port 0, and before that fix the port rode
        into the `url` column of the Catalogue sheet *and* of products.csv,
        which is why the CSV is asserted here too rather than in its own test.
    """

    def _run(self, repo, monkeypatch, state_path, out, clock, fixture="site-day2"):
        from catalog_watch import state as state_module
        from catalog_watch.cli import main

        monkeypatch.setattr(state_module, "now_utc", lambda: clock)
        argv = [
            "--serve",
            str(repo / "fixtures" / fixture),
            "--site",
            str(repo / "sites" / "fixture.json"),
            "--state",
            str(state_path),
            "--out",
            str(out),
            "--quiet",
        ]
        if not out.name.startswith("baseline"):
            # Neither compared run may write state, or the second would read
            # the first's and report a different set of changes — a real
            # difference, and nothing to do with reproducibility.
            argv.append("--no-state")
        assert main(argv) == 0
        return out

    def _two_runs(self, repo, tmp_path, monkeypatch):
        state_path = tmp_path / "state.json"
        self._run(
            repo, monkeypatch, state_path, tmp_path / "baseline",
            "2026-03-01T06:00:00+00:00", fixture="site",
        )
        first = self._run(
            repo, monkeypatch, state_path, tmp_path / "first",
            "2026-03-02T06:00:00+00:00",
        )
        second = self._run(
            repo, monkeypatch, state_path, tmp_path / "second",
            "2026-03-03T06:00:00+00:00",
        )
        return first, second

    def _two_runs_over_moving_baselines(self, repo, tmp_path, monkeypatch):
        """`_two_runs`, inverted: the baseline's clock moves and this run's
        does not.

        `_two_runs` shares one baseline, so the Run sheet's second timestamp —
        `compared against the run at <clock>` — is identical in both of its
        runs and never gets asserted about. A real `make run` writes a fresh
        baseline on every pass, so that cell moves there too. Moving only the
        older clock isolates it: whatever differs below is the baseline's
        timestamp and nothing else.
        """
        runs = []
        for tag, baseline_clock in (
            ("a", "2026-03-01T06:00:00+00:00"),
            ("b", "2026-03-01T18:30:00+00:00"),
        ):
            state_path = tmp_path / f"state_{tag}.json"
            self._run(
                repo, monkeypatch, state_path, tmp_path / f"baseline_{tag}",
                baseline_clock, fixture="site",
            )
            runs.append(
                self._run(
                    repo, monkeypatch, state_path, tmp_path / f"day2_{tag}",
                    "2026-03-02T06:00:00+00:00",
                )
            )
        return runs

    def test_the_previous_runs_clock_is_confined_to_the_run_sheet(
        self, repo, tmp_path, monkeypatch
    ):
        """Move the baseline's clock and the Catalogue sheet, the Changes
        sheet and the CSV must not notice.

        Without this, the previous-run timestamp could migrate out of the Run
        sheet — into a Catalogue header, say — and the suite would stay green,
        because every other test here compares two runs that share a baseline.
        `make run` would then have a second moving member and no test to say so.
        """
        first, second = self._two_runs_over_moving_baselines(repo, tmp_path, monkeypatch)
        run_sheet = sheet_members(first / "products.xlsx")["Run"]

        with zipfile.ZipFile(first / "products.xlsx") as a, zipfile.ZipFile(
            second / "products.xlsx"
        ) as b:
            assert a.namelist() == b.namelist()
            moved = [name for name in a.namelist() if a.read(name) != b.read(name)]
            before, after = a.read(run_sheet), b.read(run_sheet)

        # Named first: the equality below is vacuous if the clock we moved
        # never reached the sheet, which is exactly what a passing-but-empty
        # version of this test would look like.
        assert b"compared against the run at 2026-03-01T06:00:00+00:00" in before
        assert b"compared against the run at 2026-03-01T18:30:00+00:00" in after
        assert moved == [run_sheet], RUN_SHEET_IS_DELIBERATE_PROVENANCE
        assert (first / "products.csv").read_bytes() == (
            second / "products.csv"
        ).read_bytes()

    def test_only_the_run_sheet_differs_across_two_runs(self, repo, tmp_path, monkeypatch):
        """Member by member, so a failure names what moved instead of saying
        the files differ."""
        first, second = self._two_runs(repo, tmp_path, monkeypatch)
        run_sheet = sheet_members(first / "products.xlsx")["Run"]
        assert sheet_members(second / "products.xlsx")["Run"] == run_sheet

        with zipfile.ZipFile(first / "products.xlsx") as a, zipfile.ZipFile(
            second / "products.xlsx"
        ) as b:
            assert a.namelist() == b.namelist()
            moved = [name for name in a.namelist() if a.read(name) != b.read(name)]

        # Equality, not a subset: `moved == []` means the clock did not move
        # and this test proved nothing, so a static clock fails here too.
        assert moved == [run_sheet], RUN_SHEET_IS_DELIBERATE_PROVENANCE

    def test_the_run_sheet_moves_because_of_the_clock_and_nothing_else(
        self, repo, tmp_path, monkeypatch
    ):
        """The exemption names one cause. Pinning it to the timestamps keeps
        the sheet from quietly becoming a place other per-run noise can hide.
        """
        first, second = self._two_runs(repo, tmp_path, monkeypatch)
        run_sheet = sheet_members(first / "products.xlsx")["Run"]
        with zipfile.ZipFile(first / "products.xlsx") as a, zipfile.ZipFile(
            second / "products.xlsx"
        ) as b:
            before, after = a.read(run_sheet), b.read(run_sheet)

        assert b"run at   2026-03-02T06:00:00+00:00" in before
        assert b"run at   2026-03-03T06:00:00+00:00" in after
        # The two differ only where the timestamp is: put one clock back and
        # the sheets are identical.
        assert before.replace(b"2026-03-02T06:00", b"2026-03-03T06:00") == after

    def test_the_csv_is_byte_identical_across_two_runs(self, repo, tmp_path, monkeypatch):
        """No exemption here: products.csv carries the url column and no clock,
        so the ephemeral-port fix makes it fully `cmp`-green."""
        first, second = self._two_runs(repo, tmp_path, monkeypatch)
        assert (first / "products.csv").read_bytes() == (
            second / "products.csv"
        ).read_bytes()

    def test_the_text_summary_moves_only_where_the_workbook_does(
        self, repo, tmp_path, monkeypatch
    ):
        """`make run` advertises three files; this class was asserting two.

        `out/changes.txt` is the same summary the Run sheet copies, so it
        carries the same clock and is exempt for the same reason — but only
        for that reason. Asserted line by line rather than with `cmp`, so the
        exemption is the two timestamps and not the whole file.
        """
        first, second = self._two_runs(repo, tmp_path, monkeypatch)
        before = (first / "changes.txt").read_text(encoding="utf-8").splitlines()
        after = (second / "changes.txt").read_text(encoding="utf-8").splitlines()
        assert len(before) == len(after)

        moved = [(a, b) for a, b in zip(before, after) if a != b]
        assert moved == [
            (
                "  run at   2026-03-02T06:00:00+00:00",
                "  run at   2026-03-03T06:00:00+00:00",
            )
        ], RUN_SHEET_IS_DELIBERATE_PROVENANCE

    def test_the_url_column_carries_no_port(self, repo, tmp_path, monkeypatch):
        """Named directly, because the test above would also pass if the port
        were stable for an unrelated reason — a fixed port, say, which would
        bring back the collisions `serve.py` binds port 0 to avoid."""
        first, _ = self._two_runs(repo, tmp_path, monkeypatch)
        text = (first / "products.csv").read_text(encoding="utf-8")
        assert f"{FIXTURE_ORIGIN}/products/TW-1004.html" in text
        assert not re.search(r"127\.0\.0\.1:\d+", text)
