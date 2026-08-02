from __future__ import annotations

import gzip
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib
from dataclasses import dataclass
from typing import Any


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status: int
    text: str
    content_type: str


class HttpClient:
    def __init__(self, user_agent: str, timeout_seconds: int = 25) -> None:
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _decode(self, body: bytes, headers: Any) -> str:
        encoding = (headers.get("Content-Encoding") or "").casefold()
        if encoding == "gzip":
            body = gzip.decompress(body)
        elif encoding == "deflate":
            body = zlib.decompress(body)
        charset = headers.get_content_charset() or "utf-8"
        try:
            return body.decode(charset, errors="replace")
        except LookupError:
            return body.decode("utf-8", errors="replace")

    def fetch(self, url: str, accept: str = "text/html,application/xhtml+xml") -> FetchResponse:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": accept,
                "Accept-Encoding": "gzip, deflate",
                "Accept-Language": "en-US,en;q=0.8",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read(12_000_000)
                return FetchResponse(
                    url=response.geturl(),
                    status=int(response.status),
                    text=self._decode(body, response.headers),
                    content_type=response.headers.get("Content-Type", ""),
                )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            raise FetchError(f"{type(exc).__name__}: {exc}") from exc

    def robots(self, root_url: str) -> urllib.robotparser.RobotFileParser | None:
        parsed = urllib.parse.urlsplit(root_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        robots_url = urllib.parse.urljoin(origin, "/robots.txt")
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = self.fetch(robots_url, accept="text/plain,*/*")
            parser.parse(response.text.splitlines())
            self._robots[origin] = parser
        except FetchError:
            self._robots[origin] = None
        return self._robots[origin]

    def can_fetch(self, root_url: str, url: str) -> bool:
        parser = self.robots(root_url)
        return True if parser is None else parser.can_fetch(self.user_agent, url)


class BrowserRenderer:
    """One Chromium instance shared by a run. Playwright is imported lazily."""

    def __init__(self, timeout_seconds: int = 35) -> None:
        self.timeout_ms = timeout_seconds * 1000
        self._manager: Any = None
        self._browser: Any = None
        self._context: Any = None

    def __enter__(self) -> "BrowserRenderer":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise FetchError(
                "Playwright is not installed. Run: pip install -e . && playwright install chromium"
            ) from exc
        self._manager = sync_playwright().start()
        self._browser = self._manager.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            locale="en-US",
            viewport={"width": 1440, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
            ),
        )
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._manager:
            self._manager.stop()

    def render(self, url: str, interactive_inventory: bool = False) -> FetchResponse:
        if self._context is None:
            raise FetchError("BrowserRenderer must be used as a context manager")
        page = self._context.new_page()
        page.set_default_timeout(self.timeout_ms)

        def block_heavy(route: Any) -> None:
            if route.request.resource_type in {"image", "media", "font"}:
                route.abort()
            else:
                route.continue_()

        page.route("**/*", block_heavy)
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(1800)
            self._dismiss_cookies(page)
            if interactive_inventory:
                self._expand_inventory(page)
            return FetchResponse(
                url=page.url,
                status=response.status if response else 200,
                text=page.content(),
                content_type="text/html; rendered=playwright",
            )
        except Exception as exc:
            raise FetchError(f"browser: {type(exc).__name__}: {exc}") from exc
        finally:
            page.close()

    def _dismiss_cookies(self, page: Any) -> None:
        selectors = (
            "button:has-text('Accept All')",
            "button:has-text('Accept')",
            "button:has-text('I Agree')",
            "button:has-text('Continue')",
        )
        for selector in selectors:
            try:
                button = page.locator(selector).first
                if button.is_visible(timeout=500):
                    button.click(timeout=1000)
                    break
            except Exception:
                continue

    def _expand_inventory(self, page: Any) -> None:
        previous_height = 0
        stable_passes = 0
        for _ in range(10):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(850)
            height = int(page.evaluate("document.body.scrollHeight"))
            if height == previous_height:
                stable_passes += 1
            else:
                stable_passes = 0
            previous_height = height
            if stable_passes >= 2:
                break

        for _ in range(5):
            clicked = False
            for label in ("Load More", "Show More", "View More"):
                try:
                    button = page.get_by_text(label, exact=False).last
                    if button.is_visible(timeout=400):
                        button.click(timeout=1200)
                        page.wait_for_timeout(900)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                break
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.1)

