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
