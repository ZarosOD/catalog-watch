"""Politeness and failure behaviour on the fetch side, against a local server."""

from __future__ import annotations

import time

import pytest

from catalog_watch.fetch import (
    FetchError,
    Fetcher,
    RobotsDisallowed,
    parse_crawl_delay,
    robots_url,
)
from catalog_watch.serve import serve_directory


@pytest.fixture
def site(repo):
    with serve_directory(repo / "fixtures" / "site") as base_url:
        yield base_url


def test_robots_url_is_derived_from_the_host():
    assert (
        robots_url("https://shop.example.com/catalogue/page2.html?x=1")
        == "https://shop.example.com/robots.txt"
    )


def test_fetches_a_page(site):
    html = Fetcher(delay=0).get(site)
    assert "Tidewater Supply Co." in html


def test_a_disallowed_path_is_refused_before_the_request(site):
    # The fixture's robots.txt disallows /cart/.
    with pytest.raises(RobotsDisallowed, match="robots.txt"):
        Fetcher(delay=0).get(site + "cart/checkout.html")


def test_the_refusal_names_the_override_flag(site):
    with pytest.raises(RobotsDisallowed, match="--ignore-robots"):
        Fetcher(delay=0).get(site + "cart/")


def test_ignore_robots_does_what_it_says(site):
    fetcher = Fetcher(delay=0, obey_robots=False)
    # Allowed past robots; the page genuinely does not exist, so it 404s.
    with pytest.raises(FetchError, match="404"):
        fetcher.get(site + "cart/")


def test_a_404_is_reported_with_the_status(site):
    with pytest.raises(FetchError, match="HTTP 404"):
        Fetcher(delay=0).get(site + "no-such-page.html")


def test_a_404_is_not_retried(site):
    # An answer, not a wobble. Retrying it wastes the site's time and ours.
    fetcher = Fetcher(delay=0, retries=3)
    started = time.monotonic()
    with pytest.raises(FetchError):
        fetcher.get(site + "no-such-page.html")
    assert time.monotonic() - started < 1.0


def test_the_delay_is_honoured_between_requests(site):
    fetcher = Fetcher(delay=0.3)
    fetcher.get(site)
    started = time.monotonic()
    fetcher.get(site + "page2.html")
    assert time.monotonic() - started >= 0.25


def test_a_dead_host_fails_with_a_readable_message():
    with pytest.raises(FetchError, match="127.0.0.1:1"):
        Fetcher(delay=0, retries=0, timeout=2).get("http://127.0.0.1:1/")


def test_the_sites_crawl_delay_wins_when_it_asks_for_more(site):
    # The fixture's robots.txt asks for 0.2s. Asking politely and then ignoring
    # the answer is worse than not asking.
    assert Fetcher(delay=0).effective_delay(site) == pytest.approx(0.2)
    assert Fetcher(delay=1.0).effective_delay(site) == pytest.approx(1.0)


def test_ignore_robots_skips_the_crawl_delay_too(site):
    assert Fetcher(delay=0, obey_robots=False).effective_delay(site) == 0


class TestCrawlDelayParsing:
    """urllib.robotparser reads Crawl-delay with isdigit(), so it drops
    fractional values. We do not."""

    UA = "catalog-watch/0.1 (+x)"

    def test_fractional_delay_under_a_wildcard_group(self):
        assert parse_crawl_delay("User-agent: *\nCrawl-delay: 0.5\n", self.UA) == 0.5

    def test_integer_delay(self):
        assert parse_crawl_delay("User-agent: *\nCrawl-delay: 2\n", self.UA) == 2.0

    def test_a_group_naming_us_beats_the_wildcard(self):
        text = (
            "User-agent: *\nCrawl-delay: 10\n\n"
            "User-agent: catalog-watch\nCrawl-delay: 1\n"
        )
        assert parse_crawl_delay(text, self.UA) == 1.0

    def test_a_delay_for_somebody_else_does_not_apply_to_us(self):
        text = "User-agent: BadBot\nCrawl-delay: 30\n"
        assert parse_crawl_delay(text, self.UA) is None

    def test_two_agents_sharing_one_group(self):
        text = "User-agent: BadBot\nUser-agent: *\nCrawl-delay: 3\n"
        assert parse_crawl_delay(text, self.UA) == 3.0

    def test_no_crawl_delay_at_all(self):
        assert parse_crawl_delay("User-agent: *\nDisallow: /x\n", self.UA) is None

    def test_nonsense_value_is_ignored_not_crashed_on(self):
        assert parse_crawl_delay("User-agent: *\nCrawl-delay: soon\n", self.UA) is None

    def test_comments_are_stripped(self):
        text = "User-agent: *  # everyone\nCrawl-delay: 0.25 # be nice\n"
        assert parse_crawl_delay(text, self.UA) == 0.25
