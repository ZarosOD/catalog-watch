"""Politeness and failure behaviour on the fetch side, against a local server."""

from __future__ import annotations

import ast
import http.client
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from catalog_watch import fetch as fetch_module
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


def test_the_package_under_test_is_this_working_tree(repo):
    """A non-editable install leaves a frozen copy of the package in
    `.venv/lib/.../site-packages/`, and whether that copy or the tree answers
    `import catalog_watch` depends on how pytest was started: `make test` and
    the README's `.venv/bin/python -m pytest` both put the repo root on
    `sys.path` first, a bare `.venv/bin/pytest` does not. So the same tree can
    come out green one way and red the other. Measured on this repo
    2026-10-10: the bare console script was reading a copy three weeks old.

    Green here means the suite is reporting on the files in this checkout. It
    is a precondition for every other test in the repo, not a fetch test, and
    it lives beside the clause-order pin because that pin is the other half of
    the same question: which file is this?
    """
    imported = Path(fetch_module.__file__).resolve()
    assert imported == (repo / "catalog_watch" / "fetch.py").resolve(), (
        f"the suite imported {imported}, not this checkout. Re-install the "
        f"package editable (`.venv/bin/python -m pip install -e .`, or "
        f"`uv pip install -e .`) and re-run; until then neither a pass nor a "
        f"failure in this suite is about the code you are looking at."
    )


class _FakeHeaders:
    def get_content_charset(self):
        return "utf-8"


class _BreaksMidResponse:
    """An opener whose headers arrive fine and whose body does not.

    A local server cannot produce a truncated body or a garbage status line on
    demand, so these three cases are injected at the one seam the code has:
    the name ``catalog_watch.fetch`` calls, ``urllib.request.urlopen``. It
    counts its own calls, so a test can tell a retried attempt from a retry
    loop that was bypassed — and so every test here carries a positive control
    that the patch was actually reached.
    """

    headers = _FakeHeaders()

    def __init__(self, exc, *, at_open: bool = False) -> None:
        self.exc = exc
        self.at_open = at_open
        self.calls = 0

    def __call__(self, request, timeout=None):
        self.calls += 1
        if self.at_open:
            raise self.exc
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        raise self.exc


def _patch_opener(monkeypatch, exc, *, at_open=False) -> _BreaksMidResponse:
    opener = _BreaksMidResponse(exc, at_open=at_open)
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    return opener


def _fetcher(**kwargs) -> Fetcher:
    # obey_robots=False so the robots.txt fetch does not also hit the fake
    # opener; _robots_for swallows every exception, which would mask the case.
    return Fetcher(delay=0, timeout=1, obey_robots=False, **kwargs)


class TestBreaksAfterTheHeadersArrive:
    """urllib wraps only the request-SEND path in URLError.

    Anything that fails once the response is in hand escapes HTTPError,
    URLError and TimeoutError alike, so it used to reach the caller raw and
    skip the retry loop on attempt 1 — the three cases below are the ones
    measured escaping before `(http.client.HTTPException, OSError)` was added.
    """

    CASES = [
        pytest.param(
            http.client.IncompleteRead(b"<html>par", 400),
            False,
            "IncompleteRead",
            id="truncated_body",
        ),
        pytest.param(
            ConnectionResetError(104, "Connection reset by peer"),
            False,
            "ConnectionResetError",
            id="peer_reset_mid_read",
        ),
        pytest.param(
            http.client.BadStatusLine("\x16\x03\x01garbage"),
            True,
            "BadStatusLine",
            id="not_a_status_line",
        ),
    ]

    @pytest.mark.parametrize("exc, at_open, name", CASES)
    def test_it_comes_out_as_a_FetchError(self, monkeypatch, exc, at_open, name):
        opener = _patch_opener(monkeypatch, exc, at_open=at_open)
        with pytest.raises(FetchError) as caught:
            _fetcher(retries=0).get("http://catalogue.invalid/page1.html")
        assert opener.calls == 1, "the patched opener was never reached"
        assert "failed mid-response" in str(caught.value)
        assert name in str(caught.value)

    def test_a_truncated_body_gets_the_retries_it_deserves(self, monkeypatch):
        # The failure mode most worth retrying, and the one that used to escape
        # on attempt 1 and never see the loop at all.
        monkeypatch.setattr(fetch_module.time, "sleep", lambda _seconds: None)
        opener = _patch_opener(monkeypatch, http.client.IncompleteRead(b"half", 99))
        with pytest.raises(FetchError, match="failed mid-response"):
            _fetcher(retries=2).get("http://catalogue.invalid/")
        assert opener.calls == 3

    def test_an_HTTPError_is_still_reported_as_a_status(self, monkeypatch):
        # HTTPError is an OSError, so a mid-response clause placed above it
        # would relabel every 404 as a broken response.
        opener = _patch_opener(
            monkeypatch,
            urllib.error.HTTPError("http://catalogue.invalid/", 404, "Not Found", {}, None),
            at_open=True,
        )
        with pytest.raises(FetchError) as caught:
            _fetcher(retries=0).get("http://catalogue.invalid/gone.html")
        assert opener.calls == 1
        assert "HTTP 404" in str(caught.value)
        assert "failed mid-response" not in str(caught.value)

    def test_a_URLError_is_still_reported_by_its_reason(self, monkeypatch):
        # URLError is an OSError too, and its reason is the readable half.
        opener = _patch_opener(
            monkeypatch, urllib.error.URLError("[Errno 111] Connection refused"),
            at_open=True,
        )
        with pytest.raises(FetchError) as caught:
            _fetcher(retries=0).get("http://catalogue.invalid/")
        assert opener.calls == 1
        assert "Connection refused" in str(caught.value)
        assert "failed mid-response" not in str(caught.value)

    def test_the_clause_order_is_pinned(self):
        """The order is load-bearing and no behavioural test can see a reorder
        that happens to keep every message intact. Read off the AST of the file
        that was actually imported, so a stale copy elsewhere cannot vouch for
        this one, and from the AST rather than a grep, so a comment naming a
        clause cannot stand in for the clause.
        """
        source = Path(fetch_module.__file__).read_text(encoding="utf-8")
        get = next(
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef) and node.name == "get"
        )
        attempt = next(node for node in ast.walk(get) if isinstance(node, ast.Try))
        caught = [
            tuple(
                ast.unparse(part)
                for part in (
                    handler.type.elts
                    if isinstance(handler.type, ast.Tuple)
                    else [handler.type]
                )
            )
            for handler in attempt.handlers
        ]
        assert caught == [
            ("urllib.error.HTTPError",),
            ("urllib.error.URLError",),
            ("TimeoutError",),
            # Last, and two names: BadStatusLine is not an OSError and
            # ConnectionResetError is not an HTTPException, so neither name
            # covers the other's cases.
            ("http.client.HTTPException", "OSError"),
        ]


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
