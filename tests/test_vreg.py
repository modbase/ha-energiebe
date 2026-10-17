"""Discovering and conditionally fetching the VREG assets."""

import asyncio
import unittest

from loader import fixture, load

vreg = load("vreg")


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"", headers: dict | None = None) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise AssertionError(f"unexpected raise_for_status in test: {self.status}")

    async def text(self) -> str:
        return self._body.decode()

    async def read(self) -> bytes:
        return self._body


class FakeSession:
    """Just enough of aiohttp.ClientSession to drive the fetcher."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.requests: list[tuple[str, dict]] = []
        self.cookie_jar = self

    def clear_domain(self, domain: str) -> None:
        self.requests.append(("clear_domain", {"domain": domain}))

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append((url, dict(kwargs)))
        return self._responses.pop(0)


class TestDiscovery(unittest.TestCase):
    def test_finds_the_vtest_asset_on_the_page(self) -> None:
        html = fixture("vreg-vtest-page.html").decode()
        url = vreg.find_asset_url(html, vreg.VTEST_PATTERN)
        self.assertIn("assets.vlaamsenutsregulator.be", url)
        self.assertIn("v-test-data-exclbtw", url)
        # The real links end ".xlsx?VersionId=...", and the query is kept: it
        # pins the exact stored version the regulator is publishing today.
        self.assertTrue(url.split("?")[0].endswith(".xlsx"))
        self.assertIn("VersionId=", url)

    def test_finds_the_network_asset_on_the_page(self) -> None:
        html = fixture("vreg-nettarieven-page.html").decode()
        url = vreg.find_asset_url(html, vreg.NETWORK_PATTERN)
        self.assertIn("istributienettarieven", url)
        self.assertTrue(url.split("?")[0].endswith(".xlsx"))
        # Same page also lists the 2025 and 2024 lists, and the gas files.
        self.assertIn("2026", url)
        self.assertNotIn("aardgas", url)

    def test_an_old_file_in_a_newer_folder_does_not_win(self) -> None:
        # Exactly the shape of the real page: the current year's list lives in
        # an older folder than a superseded one.
        html = (
            '<a href="https://assets.x/2025-11/Distributienettarieven'
            '%20elektriciteit%202026.xlsx?VersionId=aaa">current</a>'
            '<a href="https://assets.x/2025-12/Distributienettarieven'
            '%20elektriciteit%202024.xlsx?VersionId=zzz">superseded</a>'
        )
        self.assertIn("2026.xlsx", vreg.find_asset_url(html, vreg.NETWORK_PATTERN))

    def test_the_newest_match_wins(self) -> None:
        html = (
            '<a href="https://assets.x/2025-10/202510-v-test-data-exclbtw.xlsx">old</a>'
            '<a href="https://assets.x/2026-10/202610-v-test-data-exclbtw v2_0.xlsx">new</a>'
        )
        self.assertIn("202610", vreg.find_asset_url(html, vreg.VTEST_PATTERN))

    def test_html_entities_in_the_href_are_decoded(self) -> None:
        html = '<a href="https://assets.x/2026-10/202610-v-test-data-exclbtw&amp;v2.xlsx">x</a>'
        self.assertNotIn("&amp;", vreg.find_asset_url(html, vreg.VTEST_PATTERN))

    def test_no_match_is_an_error(self) -> None:
        with self.assertRaises(vreg.VregError):
            vreg.find_asset_url("<html>nothing here</html>", vreg.VTEST_PATTERN)


class TestFetch(unittest.TestCase):
    def setUp(self) -> None:
        self.workbook = fixture("nettarieven-2026.xlsx")
        self.page = (
            '<a href="https://assets.x/2026-01/Distributienettarieven '
            'elektriciteit 2026.xlsx">download</a>'
        )

    def load(self, session: FakeSession, cached: object = None) -> object:
        return asyncio.run(
            vreg.async_load_asset(
                session,
                page_url="https://vreg.example/nettarieven",
                pattern=vreg.NETWORK_PATTERN,
                cached=cached,
            )
        )

    def test_a_first_fetch_parses_the_workbook(self) -> None:
        session = FakeSession(
            [
                FakeResponse(200, self.page.encode()),
                FakeResponse(
                    200,
                    self.workbook,
                    {"ETag": '"abc"', "Last-Modified": "Tue, 11 Nov 2025 10:00:00 GMT"},
                ),
            ]
        )
        asset = self.load(session)
        self.assertEqual(asset.etag, '"abc"')
        self.assertIn("ELEK Overzicht laagspanning", asset.sheets)

    def test_a_304_reuses_the_cached_sheets_without_parsing(self) -> None:
        first = FakeSession(
            [FakeResponse(200, self.page.encode()), FakeResponse(200, self.workbook, {"ETag": '"abc"'})]
        )
        cached = self.load(first)
        again = FakeSession([FakeResponse(200, self.page.encode()), FakeResponse(304)])
        asset = self.load(again, cached=cached)
        self.assertIs(asset.sheets, cached.sheets)
        headers = again.requests[-1][1]["headers"]
        self.assertEqual(headers["If-None-Match"], '"abc"')

    def test_affinity_cookies_are_shed_before_each_request(self) -> None:
        session = FakeSession(
            [FakeResponse(200, self.page.encode()), FakeResponse(200, self.workbook, {})]
        )
        self.load(session)
        cleared = [r for r in session.requests if r[0] == "clear_domain"]
        self.assertTrue(cleared)

    def test_a_server_error_is_an_error_not_a_silent_empty_asset(self) -> None:
        session = FakeSession([FakeResponse(200, self.page.encode()), FakeResponse(503)])
        with self.assertRaises(vreg.VregError):
            self.load(session)

    def test_a_body_that_is_not_a_workbook_is_an_error(self) -> None:
        session = FakeSession(
            [FakeResponse(200, self.page.encode()), FakeResponse(200, b"<html>oops</html>", {})]
        )
        with self.assertRaises(vreg.VregError):
            self.load(session)


if __name__ == "__main__":
    unittest.main()
