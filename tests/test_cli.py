"""End to end, over real HTTP, against the bundled fixture.

These assert against ``tests/expected_changes.json``, which the fixture
generator writes from the same table it draws the pages from — so the test
checks the tool against the storefront, not against the tool's own output.
"""

from __future__ import annotations

import csv
import json

import pytest

from catalog_watch.cli import (
    EXIT_CHANGED,
    EXIT_FETCH,
    EXIT_OK,
    EXIT_REVIEW,
    EXIT_USAGE,
    main,
)


def run(repo, tmp_path, day, *extra):
    site = repo / "fixtures" / ("site" if day == 1 else "site-day2")
    return main(
        [
            "--serve",
            str(site),
            "--site",
            str(repo / "sites" / "fixture.json"),
            "--state",
            str(tmp_path / "state.json"),
            "--out",
            str(tmp_path / "out"),
            "--quiet",
            *extra,
        ]
    )


def read_csv(tmp_path):
    with (tmp_path / "out" / "products.csv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def changes_text(tmp_path) -> str:
    return (tmp_path / "out" / "changes.txt").read_text(encoding="utf-8")


class TestFirstRun:
    def test_writes_all_three_outputs(self, repo, tmp_path):
        assert run(repo, tmp_path, 1) == EXIT_OK
        out = tmp_path / "out"
        for name in ("products.csv", "products.xlsx", "changes.txt"):
            assert (out / name).exists(), name
            assert (out / name).stat().st_size > 0

    def test_scrapes_every_product_across_both_pages(self, repo, tmp_path, expected):
        run(repo, tmp_path, 1)
        assert len(read_csv(tmp_path)) == expected["day1_products"]

    def test_reports_a_baseline_not_thirty_new_products(self, repo, tmp_path):
        run(repo, tmp_path, 1)
        text = changes_text(tmp_path)
        assert "First run" in text
        assert "new" not in text.split("First run")[0]

    def test_the_unreadable_price_is_flagged_not_guessed(self, repo, tmp_path, expected):
        run(repo, tmp_path, 1)
        rows = {r["sku"]: r for r in read_csv(tmp_path)}
        for sku in expected["unreadable_price_skus"]:
            assert rows[sku]["price"] == ""
            assert rows[sku]["needs_review"] == "yes"
        flagged = [r for r in rows.values() if r["needs_review"] == "yes"]
        assert len(flagged) == len(expected["unreadable_price_skus"])

    def test_writes_the_state_file(self, repo, tmp_path):
        run(repo, tmp_path, 1)
        saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert saved["version"] == 1
        assert len(saved["products"]) == 30


class TestSecondRun:
    @pytest.fixture
    def after_two_runs(self, repo, tmp_path):
        run(repo, tmp_path, 1)
        run(repo, tmp_path, 2)
        return tmp_path

    def test_reports_exactly_the_expected_changes(self, after_two_runs, expected):
        text = changes_text(after_two_runs)
        assert f"{len(expected['changes'])} changes since the previous run" in text
        for change in expected["changes"]:
            assert change["sku"] in text

    def test_reports_only_the_deltas(self, after_two_runs, expected):
        rows = read_csv(after_two_runs)
        changed = [r for r in rows if r["change"]]
        assert len(changed) == len(expected["changes"])
        changed_skus = {r["sku"] for r in changed}
        assert changed_skus == {c["sku"] for c in expected["changes"]}

    def test_each_change_kind_is_named_correctly(self, after_two_runs, expected):
        rows = {r["sku"]: r for r in read_csv(after_two_runs)}
        for change in expected["changes"]:
            label = rows[change["sku"]]["change"]
            if change["kind"] == "price":
                assert label in ("price cut", "price up")
                rise = float(change["after"]) > float(change["before"])
                assert label == ("price up" if rise else "price cut")
            elif change["kind"] == "availability":
                assert label == "stock"
            else:
                assert label == change["kind"]

    def test_the_standing_review_flag_is_not_reported_as_a_change(
        self, after_two_runs, expected
    ):
        rows = {r["sku"]: r for r in read_csv(after_two_runs)}
        for sku in expected["unreadable_price_skus"]:
            assert rows[sku]["change"] == ""
            assert rows[sku]["needs_review"] == "yes"

    def test_the_delisted_product_keeps_a_row(self, after_two_runs):
        rows = {r["sku"]: r for r in read_csv(after_two_runs)}
        [delisted] = [r for r in rows.values() if r["status"] == "delisted"]
        assert delisted["change"] == "delisted"


class TestThirdRun:
    def test_rerunning_the_same_day_reports_nothing(self, repo, tmp_path):
        run(repo, tmp_path, 1)
        run(repo, tmp_path, 2)
        run(repo, tmp_path, 2)
        assert "No changes since the previous run." in changes_text(tmp_path)

    def test_no_state_leaves_the_baseline_where_it_was(self, repo, tmp_path):
        run(repo, tmp_path, 1)
        before = (tmp_path / "state.json").read_text(encoding="utf-8")
        run(repo, tmp_path, 2, "--no-state")
        assert (tmp_path / "state.json").read_text(encoding="utf-8") == before
        # ...and so the same run still reports the same deltas next time.
        run(repo, tmp_path, 2, "--no-state")
        assert "6 changes since the previous run" in changes_text(tmp_path)


class TestCategoryAndDescriptionEndToEnd:
    """THE-452, over real HTTP, through `main()`, to the files on disk.

    A two-revision storefront of its own rather than the bundled one:
    `fixtures/site` prints no category and no blurb, and giving it them would
    redraw every product card in the recorded demo — a clip re-record and a
    separate set of claims, not this card. So the profile and the pages are
    built here, and what is asserted is the real pipeline: fetch, parse, state
    file, diff, CSV, XLSX, summary.
    """

    PROFILE = {
        "name": "end-to-end test shop",
        "product": {"selector": "article.product"},
        "fields": {
            "sku": {"selector": ".sku"},
            "name": {"selector": ".product-name"},
            "price": {"selector": ".price", "parse": "money"},
            "category": {"selector": ".category"},
            "description": {"selector": ".blurb"},
        },
        "required": ["sku", "name", "price"],
    }

    #: sku, name, price, category, description. Day two moves one category,
    #: re-words one description, and blanks one category element — one of each
    #: thing this card is about, and nothing else moves.
    DAY_ONE = [
        ("E-1", "Braided Line", "48.00", "Rope &amp; Chain", "Twelve millimetre line."),
        ("E-2", "Bow Shackle", "12.75", "Rope &amp; Chain", "Forged 316 stainless."),
        ("E-3", "Bilge Pump", "62.50", "Pumps", "800 GPH, 12 volt."),
    ]
    DAY_TWO = [
        ("E-1", "Braided Line", "48.00", "Deck Hardware", "Twelve millimetre line."),
        ("E-2", "Bow Shackle", "12.75", "Rope &amp; Chain", "Forged stainless, 316."),
        ("E-3", "Bilge Pump", "62.50", "", "800 GPH, 12 volt."),
    ]

    def _site(self, root, rows, name):
        directory = root / name
        directory.mkdir(parents=True)
        cards = "\n".join(
            f'<article class="product">'
            f'<p class="sku">{sku}</p>'
            f'<h2 class="product-name">{product_name}</h2>'
            f'<p class="price">${price}</p>'
            f'<p class="category">{category}</p>'
            f'<p class="blurb">{blurb}</p>'
            f"</article>"
            for sku, product_name, price, category, blurb in rows
        )
        (directory / "index.html").write_text(
            f"<!doctype html><html><body><main>{cards}</main></body></html>",
            encoding="utf-8",
        )
        return directory

    @pytest.fixture
    def two_runs(self, tmp_path):
        site = tmp_path / "site"
        day1 = self._site(site, self.DAY_ONE, "day1")
        day2 = self._site(site, self.DAY_TWO, "day2")
        profile = tmp_path / "profile.json"
        profile.write_text(json.dumps(self.PROFILE), encoding="utf-8")

        def run(directory, out):
            return main(
                ["--serve", str(directory), "--site", str(profile),
                 "--state", str(tmp_path / "state.json"),
                 "--out", str(tmp_path / out), "--quiet"]
            )

        first = run(day1, "out1")
        second = run(day2, "out2")
        return first, second, tmp_path

    def test_the_profile_loads_and_the_first_run_is_clean(self, two_runs):
        """Before this card a profile naming either field raised
        SiteConfigError at load, which `main()` turns into EXIT_USAGE."""
        first, _, _ = two_runs
        assert first == EXIT_OK

    def test_both_fields_reach_the_csv(self, two_runs):
        _, _, tmp_path = two_runs
        with (tmp_path / "out1" / "products.csv").open(encoding="utf-8") as handle:
            rows = {r["sku"]: r for r in csv.DictReader(handle)}
        assert rows["E-1"]["category"] == "Rope & Chain"
        assert rows["E-1"]["description"] == "Twelve millimetre line."
        assert rows["E-3"]["category"] == "Pumps"

    def test_both_fields_reach_the_xlsx_catalogue_sheet(self, two_runs):
        openpyxl = pytest.importorskip("openpyxl")
        _, _, tmp_path = two_runs
        catalogue = openpyxl.load_workbook(
            tmp_path / "out1" / "products.xlsx"
        )["Catalogue"]
        header = [c.value for c in catalogue[1]]
        values = {
            catalogue.cell(row=r, column=header.index("sku") + 1).value: (
                catalogue.cell(row=r, column=header.index("category") + 1).value,
                catalogue.cell(row=r, column=header.index("description") + 1).value,
            )
            for r in range(2, catalogue.max_row + 1)
        }
        assert values["E-1"] == ("Rope & Chain", "Twelve millimetre line.")
        assert values["E-3"] == ("Pumps", "800 GPH, 12 volt.")

    def test_both_fields_survive_the_state_file(self, two_runs):
        """The round trip the diff depends on: `Product.to_json` names its
        fields explicitly, so a field missing from it reads back as None and
        the next run reports a change that did not happen."""
        _, _, tmp_path = two_runs
        saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        by_sku = {p["sku"]: p for p in saved["products"]}
        assert by_sku["E-2"]["category"] == "Rope & Chain"
        assert by_sku["E-2"]["description"] == "Forged stainless, 316."

    def test_the_category_move_is_the_reported_change(self, two_runs):
        _, second, tmp_path = two_runs
        with (tmp_path / "out2" / "products.csv").open(encoding="utf-8") as handle:
            rows = {r["sku"]: r for r in csv.DictReader(handle)}
        assert rows["E-1"]["change"] == "category"
        assert "Rope & Chain -> Deck Hardware" in rows["E-1"]["change_detail"]
        # E-3's blanked category is flagged, and a flagged product is still a
        # finished run: the exit code only moves under --fail-on-review.
        assert second == EXIT_OK

    def test_the_rewritten_description_is_not_reported(self, two_runs):
        """E-2's blurb changed and nothing else about E-2 did."""
        _, _, tmp_path = two_runs
        with (tmp_path / "out2" / "products.csv").open(encoding="utf-8") as handle:
            rows = {r["sku"]: r for r in csv.DictReader(handle)}
        assert rows["E-2"]["change"] == ""
        assert rows["E-2"]["description"] == "Forged stainless, 316."

    def test_a_category_that_stops_reading_is_flagged_not_defaulted(self, two_runs):
        _, _, tmp_path = two_runs
        with (tmp_path / "out2" / "products.csv").open(encoding="utf-8") as handle:
            rows = {r["sku"]: r for r in csv.DictReader(handle)}
        assert rows["E-3"]["category"] == ""
        assert rows["E-3"]["needs_review"] == "yes"
        assert "category: empty" in rows["E-3"]["issues"]
        assert rows["E-3"]["change"] == "unreadable"
        # Not the previous run's value, and not the neighbouring field's.
        assert "Pumps" not in rows["E-3"]["category"]

    def test_the_summary_reports_the_category_move_and_not_the_rewording(
        self, two_runs
    ):
        _, _, tmp_path = two_runs
        text = (tmp_path / "out2" / "changes.txt").read_text(encoding="utf-8")
        assert "2 changes since the previous run" in text
        assert "category" in text
        assert "Rope & Chain -> Deck Hardware" in text
        assert "Forged stainless" not in text


class TestExitCodes:
    def test_clean_run_is_zero(self, repo, tmp_path):
        assert run(repo, tmp_path, 1) == EXIT_OK

    def test_fail_on_review(self, repo, tmp_path):
        assert run(repo, tmp_path, 1, "--fail-on-review") == EXIT_REVIEW

    def test_fail_on_change_is_quiet_on_the_first_run(self, repo, tmp_path):
        assert run(repo, tmp_path, 1, "--fail-on-change") == EXIT_OK

    def test_fail_on_change_fires_on_the_second(self, repo, tmp_path):
        run(repo, tmp_path, 1)
        assert run(repo, tmp_path, 2, "--fail-on-change") == EXIT_CHANGED

    def test_both_a_url_and_serve_is_a_usage_error(self, repo, tmp_path, capsys):
        assert main(["http://example.test/", "--serve", "x", "--quiet"]) == EXIT_USAGE
        assert "not both" in capsys.readouterr().err

    def test_neither_is_a_usage_error(self):
        assert main(["--quiet"]) == EXIT_USAGE

    def test_a_bad_site_profile_is_a_usage_error(self, repo, tmp_path, capsys):
        bad = tmp_path / "bad.json"
        bad.write_text('{"product": {"selector": ".p"}, "fields": {}}', encoding="utf-8")
        code = main(["--serve", str(repo / "fixtures" / "site"), "--site", str(bad), "--quiet"])
        assert code == EXIT_USAGE
        assert "sku" in capsys.readouterr().err

    def test_an_unreachable_host_exits_with_the_fetch_code(self, repo, tmp_path, capsys):
        # Port 1 on loopback: nothing listens there, and it fails fast.
        code = main(
            [
                "http://127.0.0.1:1/",
                "--site",
                str(repo / "sites" / "fixture.json"),
                "--state",
                str(tmp_path / "state.json"),
                "--out",
                str(tmp_path / "out"),
                "--quiet",
                "--timeout",
                "2",
            ]
        )
        assert code == EXIT_FETCH
        assert "watch.py:" in capsys.readouterr().err
