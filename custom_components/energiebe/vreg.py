"""Fetch the VREG spreadsheets the tariff components come from.

Two files, on very different schedules: the V-test is republished monthly, the
distribution network tariffs once a year. Both are linked from a plain
server-rendered page at a URL that embeds a dated folder and a version suffix,
so the link is read off the page instead of being guessed, and both answer with
``ETag``, so the daily tick asks conditionally and only parses on a 200.

Knows nothing about Home Assistant: it takes a session and returns parsed
sheets, which is what makes it testable without one.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp

from .xlsx import XlsxError, read_xlsx

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=60)

# The two assets, by the part of their file name that identifies them. Matching
# on the whole href keeps the dated folder out of our hands.
VTEST_PATTERN = re.compile(r"v-test-data-exclbtw", re.IGNORECASE)
NETWORK_PATTERN = re.compile(r"distributienettarieven.*?elektriciteit", re.IGNORECASE)
# Note the non-greedy any rather than \D*: the hrefs are URL-encoded, so the
# space between the two words arrives as "%20" and carries digits.

_HREF = re.compile(r'href="([^"]+\.xlsx[^"]*)"', re.IGNORECASE)
_NUMBER = re.compile(r"\d+")


class VregError(Exception):
    """Raised when an asset cannot be found, fetched or read."""


@dataclass(frozen=True)
class Asset:
    """One fetched workbook, with what is needed to ask about it again."""

    url: str
    etag: str | None
    last_modified: str | None
    sheets: dict[str, list[list[str]]]


def _recency(href: str) -> tuple[int, str]:
    """Rank one candidate link: biggest number in its path, then the path.

    VREG dates an asset twice -- a yyyy-mm folder and a number in the file name
    (202610 for a V-test month, 2026 for a tariff year) -- and the folder is not
    the one to trust: the 2026 network tariff list is published under /2025-11/,
    in the same folder as a 2024 list. The biggest number in the path tracks what
    the document is about rather than when someone uploaded it. The query string
    is excluded because the links carry an opaque ?VersionId= full of digits.
    """
    path = href.split("?", 1)[0]
    numbers = [int(match.group()) for match in _NUMBER.finditer(path)]
    return (max(numbers) if numbers else 0, path)


def find_asset_url(page: str, pattern: re.Pattern[str]) -> str:
    """Return the newest matching .xlsx link on a VREG page.

    The link is returned as the page gives it, query string included: it pins the
    exact stored version VREG currently publishes, which is the document we want
    to be reading.
    """
    matches = [href for href in _HREF.findall(page) if pattern.search(href)]
    if not matches:
        raise VregError(f"No .xlsx link matching {pattern.pattern!r} on the page")
    return html.unescape(max(matches, key=_recency))


async def _async_get(
    session: aiohttp.ClientSession, url: str, headers: dict[str, str] | None = None
) -> tuple[int, bytes, dict[str, str]]:
    """GET a URL, shedding any load-balancer affinity cookie first."""
    if host := urlparse(url).hostname:
        # Same hygiene as the tariff scrape: HA's session keeps cookies for the
        # life of the process, so one bad instance would otherwise stick.
        session.cookie_jar.clear_domain(host)
    try:
        async with session.get(url, headers=headers or {}, timeout=_TIMEOUT) as response:
            if response.status == 304:
                return 304, b"", dict(response.headers)
            if response.status >= 400:
                raise VregError(f"{url} answered {response.status}")
            return response.status, await response.read(), dict(response.headers)
    except (TimeoutError, aiohttp.ClientError) as err:
        raise VregError(f"Error fetching {url}: {err}") from err


async def async_load_asset(
    session: aiohttp.ClientSession,
    *,
    page_url: str,
    pattern: re.Pattern[str],
    cached: Asset | None = None,
) -> Asset:
    """Return the current workbook, reusing ``cached`` when it is unchanged."""
    _, body, _ = await _async_get(session, page_url)
    url = find_asset_url(body.decode(errors="replace"), pattern)

    headers: dict[str, str] = {}
    if cached is not None and cached.url == url:
        if cached.etag:
            headers["If-None-Match"] = cached.etag
        elif cached.last_modified:
            headers["If-Modified-Since"] = cached.last_modified

    status, data, response_headers = await _async_get(session, url, headers)
    if status == 304 and cached is not None:
        _LOGGER.debug("%s is unchanged", url)
        return cached

    try:
        sheets = read_xlsx(data)
    except XlsxError as err:
        raise VregError(f"{url} is not a workbook we can read: {err}") from err

    return Asset(
        url=url,
        etag=response_headers.get("ETag"),
        last_modified=response_headers.get("Last-Modified"),
        sheets=sheets,
    )
