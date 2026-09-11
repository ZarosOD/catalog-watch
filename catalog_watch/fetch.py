"""Getting pages, politely.

stdlib ``urllib`` rather than ``requests``: one fewer dependency for something
that does GETs against one host.

Politeness is not decoration on a scraping tool — it is the difference between
a job that runs every morning for a year and one that gets the client's IP
blocked in week two. So: a real User-Agent that says who is calling, a delay
between requests, a page cap, and robots.txt checked before the first fetch.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

USER_AGENT = "catalog-watch/0.1 (+scheduled catalogue diff; contact: you@example.com)"

# Worth one retry: the server is briefly unhappy. A 404 or a 403 is an answer.
RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    """A page could not be fetched. Carries enough detail to act on."""


class RobotsDisallowed(FetchError):
    pass


def robots_url(url: str) -> str:
    parts = urlparse(url)
    return urlunparse((parts.scheme, parts.netloc, "/robots.txt", "", "", ""))


def parse_crawl_delay(text: str, user_agent: str) -> float | None:
    """The Crawl-delay that applies to us, in seconds.

    ``urllib.robotparser`` reads Crawl-delay with ``isdigit()``, so it drops
    "Crawl-delay: 0.5" on the floor and reports no delay at all. Sites do
    publish fractional delays, and quietly ignoring one is exactly the kind of
    rudeness that gets a scraper blocked, so it is parsed here instead.
    """
    token = user_agent.split("/")[0].strip().lower()
    delays: dict[str, float] = {}
    agents: list[str] = []
    collecting = False

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()

        if key == "user-agent":
            if not collecting:
                agents = []
            agents.append(value.lower())
            collecting = True
            continue

        collecting = False
        if key == "crawl-delay" and agents:
            try:
                delay = float(value)
            except ValueError:
                continue
            for agent in agents:
                delays.setdefault(agent, delay)

    if token in delays:
        return delays[token]
    return delays.get("*")


class Fetcher:
    def __init__(
        self,
        *,
        user_agent: str = USER_AGENT,
        delay: float = 0.5,
        timeout: float = 15.0,
        retries: int = 1,
        obey_robots: bool = True,
    ) -> None:
        self.user_agent = user_agent
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.obey_robots = obey_robots
        # host -> (rules, crawl_delay), or None when the host has no robots.txt.
        self._robots: dict[str, tuple[RobotFileParser, float | None] | None] = {}
        self._last_request: float | None = None

    def _robots_for(self, url: str) -> tuple[RobotFileParser, float | None] | None:
        host = urlparse(url).netloc
        if host in self._robots:
            return self._robots[host]

        entry = None
        request = urllib.request.Request(
            robots_url(url), headers={"User-Agent": self.user_agent}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                text = response.read().decode(charset, errors="replace")
        except Exception:
            # No robots.txt, or it could not be fetched. The convention is that
            # this means "no restrictions"; we do not invent stricter ones.
            text = None

        if text is not None:
            parser = RobotFileParser()
            parser.parse(text.splitlines())
            entry = (parser, parse_crawl_delay(text, self.user_agent))

        self._robots[host] = entry
        return entry

    def allowed(self, url: str) -> bool:
        if not self.obey_robots:
            return True
        entry = self._robots_for(url)
        if entry is None:
            return True
        return entry[0].can_fetch(self.user_agent, url)

    def effective_delay(self, url: str) -> float:
        """Our own delay, or the site's Crawl-delay if it asks for more.

        Asking politely and then ignoring the answer is worse than not asking.
        --ignore-robots skips this too: it means "do not read robots.txt", not
        "read it selectively".
        """
        if not self.obey_robots:
            return self.delay
        entry = self._robots_for(url)
        if entry is None or entry[1] is None:
            return self.delay
        return max(self.delay, entry[1])

    def _wait(self, delay: float) -> None:
        if delay <= 0 or self._last_request is None:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < delay:
            time.sleep(delay - elapsed)

    def get(self, url: str) -> str:
        if not self.allowed(url):
            raise RobotsDisallowed(
                f"{url} is disallowed by {robots_url(url)} for "
                f"{self.user_agent.split('/')[0]}. Pass --ignore-robots only if "
                f"you have the site owner's agreement."
            )

        delay = self.effective_delay(url)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait(delay)
            request = urllib.request.Request(
                url, headers={"User-Agent": self.user_agent, "Accept": "text/html"}
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    self._last_request = time.monotonic()
                    charset = response.headers.get_content_charset() or "utf-8"
                    return response.read().decode(charset, errors="replace")
            except urllib.error.HTTPError as exc:
                self._last_request = time.monotonic()
                last_error = exc
                if exc.code not in RETRY_STATUSES or attempt == self.retries:
                    raise FetchError(f"{url}: HTTP {exc.code} {exc.reason}") from None
            except urllib.error.URLError as exc:
                self._last_request = time.monotonic()
                last_error = exc
                if attempt == self.retries:
                    raise FetchError(f"{url}: {exc.reason}") from None
            except TimeoutError:
                self._last_request = time.monotonic()
                last_error = TimeoutError()
                if attempt == self.retries:
                    raise FetchError(f"{url}: timed out after {self.timeout}s") from None
            time.sleep(min(2.0 * (attempt + 1), 5.0))

        raise FetchError(f"{url}: {last_error}")
