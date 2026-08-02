from __future__ import annotations

import time
from contextlib import nullcontext
from datetime import UTC, datetime

from .config import Config
from .discovery import discover_from_sitemaps
from .models import Dealer, DealerResult, Vehicle
from .parser import (
    deduplicate,
    discover_inventory_links,
    extract_candidate_links,
    parse_inventory_html,
)
from .web import BrowserRenderer, FetchError, HttpClient


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class InventoryScraper:
    def __init__(self, config: Config, use_browser: bool = True) -> None:
        self.config = config
        self.use_browser = use_browser
        self.http = HttpClient(
            user_agent=config.settings.user_agent,
            timeout_seconds=config.settings.request_timeout_seconds,
        )

    def scrape_all(self, dealer_ids: set[str] | None = None) -> list[DealerResult]:
        dealers = [
            dealer
            for dealer in self.config.dealers
            if dealer.enabled and (dealer_ids is None or dealer.id in dealer_ids)
        ]
        results: list[DealerResult] = []
        browser_context = (
            BrowserRenderer(self.config.settings.browser_timeout_seconds)
            if self.use_browser
            else nullcontext(None)
        )
        try:
            with browser_context as browser:
                for index, dealer in enumerate(dealers):
                    print(f"[{index + 1}/{len(dealers)}] {dealer.name}", flush=True)
                    results.append(self.scrape_dealer(dealer, browser))
                    if index + 1 < len(dealers):
                        time.sleep(self.config.settings.pause_between_dealers_seconds)
        except FetchError as exc:
            # If Chromium cannot start, still attempt a standards-only scrape.
            print(f"Browser unavailable ({exc}); continuing with HTTP and sitemaps", flush=True)
            results = []
            for index, dealer in enumerate(dealers):
                print(f"[{index + 1}/{len(dealers)}] {dealer.name} (HTTP only)", flush=True)
                results.append(self.scrape_dealer(dealer, None))
        return results

    def scrape_dealer(self, dealer: Dealer, browser: BrowserRenderer | None) -> DealerResult:
        checked_at = utc_now()
        errors: list[str] = []
        methods: list[str] = []
        pages_checked = 0
        vehicles: list[Vehicle] = []
        inventory_urls = list(dealer.inventory_urls)

        sitemap = discover_from_sitemaps(self.http, dealer.url, self.config.target)
        pages_checked += sitemap.documents_checked
        if not sitemap.searched:
            errors.extend(sitemap.errors)
        if sitemap.searched:
            methods.append("vehicle sitemap")

        homepage_source = ""
        if self.http.can_fetch(dealer.url, dealer.url):
            try:
                homepage = self.http.fetch(dealer.url)
                pages_checked += 1
                homepage_source = homepage.text
                inventory_urls.extend(
                    discover_inventory_links(homepage.text, homepage.url, self.config.target)
                )
            except FetchError as exc:
                errors.append(f"homepage: {exc}")
        else:
            errors.append("homepage disallowed by robots.txt")

        # Sitemap VDPs are the most complete and least expensive source.
        candidate_urls = list(sitemap.candidate_urls)
        max_pages = self.config.settings.max_vehicle_pages_per_dealer
        rendered_failures: list[str] = []
        for candidate_url in candidate_urls[:max_pages]:
            if not self.http.can_fetch(dealer.url, candidate_url):
                errors.append(f"VDP disallowed by robots.txt: {candidate_url}")
                continue
            parsed: list[Vehicle] = []
            try:
                response = self.http.fetch(candidate_url)
                pages_checked += 1
                parsed = parse_inventory_html(
                    response.text, response.url, dealer, self.config.target
                )
            except FetchError as exc:
                rendered_failures.append(f"{candidate_url}: {exc}")
            if not parsed and browser is not None and len(rendered_failures) < 9:
                try:
                    response = browser.render(candidate_url)
                    pages_checked += 1
                    parsed = parse_inventory_html(
                        response.text, response.url, dealer, self.config.target
                    )
                except FetchError as exc:
                    rendered_failures.append(f"{candidate_url}: {exc}")
            vehicles.extend(parsed)
        if candidate_urls:
            methods.append("vehicle detail pages")
        errors.extend(rendered_failures[-5:])

        # When no usable VDP sitemap exists, render the site's own inventory search.
        rendered_inventory = False
        if not sitemap.searched or (candidate_urls and not vehicles):
            if not inventory_urls and browser is not None:
                try:
                    rendered_home = browser.render(dealer.url)
                    pages_checked += 1
                    homepage_source = rendered_home.text
                    inventory_urls.extend(
                        discover_inventory_links(
                            rendered_home.text, rendered_home.url, self.config.target
                        )
                    )
                except FetchError as exc:
                    errors.append(f"rendered homepage: {exc}")

            for inventory_url in list(dict.fromkeys(inventory_urls))[:3]:
                if not self.http.can_fetch(dealer.url, inventory_url):
                    errors.append(f"inventory page disallowed by robots.txt: {inventory_url}")
                    continue
                try:
                    if browser is not None:
                        response = browser.render(inventory_url, interactive_inventory=True)
                    else:
                        response = self.http.fetch(inventory_url)
                    pages_checked += 1
                    rendered_inventory = True
                    methods.append("rendered dealer inventory" if browser else "dealer inventory HTML")
                    vehicles.extend(
                        parse_inventory_html(
                            response.text, response.url, dealer, self.config.target
                        )
                    )
                    new_links = extract_candidate_links(
                        response.text, response.url, self.config.target
                    )
                    for link in new_links:
                        if link not in candidate_urls:
                            candidate_urls.append(link)
                except FetchError as exc:
                    errors.append(f"inventory {inventory_url}: {exc}")

            # Fetch VDP links discovered inside the rendered search page.
            already = set(sitemap.candidate_urls)
            for candidate_url in [url for url in candidate_urls if url not in already][:max_pages]:
                try:
                    response = self.http.fetch(candidate_url)
                    pages_checked += 1
                    vehicles.extend(
                        parse_inventory_html(
                            response.text, response.url, dealer, self.config.target
                        )
                    )
                except FetchError as exc:
                    errors.append(f"VDP {candidate_url}: {exc}")

        vehicles = deduplicate(vehicles)
        for vehicle in vehicles:
            vehicle.checked_at = checked_at
            vehicle.last_seen = checked_at

        complete_source = sitemap.searched or rendered_inventory
        if complete_source and errors:
            status = "partial"
        elif complete_source:
            status = "ok"
        else:
            status = "failed"

        if status == "failed":
            message = "Could not verify the dealer's complete new inventory"
        elif errors:
            message = f"Completed with {len(errors)} warning(s)"
        elif vehicles:
            message = f"Found {len(vehicles)} matching vehicle(s)"
        else:
            message = "No matching vehicles found"

        if errors:
            message += "; " + " | ".join(errors[-2:])[:500]

        return DealerResult(
            dealer=dealer,
            status=status,
            vehicles=vehicles,
            checked_at=checked_at,
            method=", ".join(dict.fromkeys(methods)) or "none",
            message=message,
            pages_checked=pages_checked,
            candidate_urls=len(candidate_urls),
        )
