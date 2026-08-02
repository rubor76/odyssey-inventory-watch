from __future__ import annotations

import re
import urllib.parse
from collections import deque
from dataclasses import dataclass

from lxml import etree

from .models import Target
from .web import FetchError, HttpClient


SITEMAP_RE = re.compile(r"^\s*Sitemap\s*:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)


@dataclass
class SitemapResult:
    candidate_urls: list[str]
    searched: bool
    documents_checked: int
    errors: list[str]


def sitemap_seeds(client: HttpClient, root_url: str) -> list[str]:
    parsed = urllib.parse.urlsplit(root_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    seeds: list[str] = []
    try:
        robots = client.fetch(urllib.parse.urljoin(origin, "/robots.txt"), accept="text/plain,*/*")
        seeds.extend(SITEMAP_RE.findall(robots.text))
    except FetchError:
        pass
    seeds.extend(
        urllib.parse.urljoin(origin, path)
        for path in (
            "/sitemap.xml",
            "/sitemap_index.xml",
            "/sitemap-index.xml",
            "/vehicle-sitemap.xml",
            "/inventory-sitemap.xml",
        )
    )
    return list(dict.fromkeys(seeds))


def sitemap_child_score(url: str) -> int:
    folded = url.casefold()
    if any(token in folded for token in ("image", "video", "news", "blog", "post", "staff")):
        return -100
    score = 0
    if any(token in folded for token in ("vehicle", "inventory", "vdp", "auto")):
        score += 100
    if "new" in folded:
        score += 30
    if "used" in folded or "preowned" in folded:
        score -= 80
    if "sitemap" in folded:
        score += 5
    return score


def target_entry(text: str, target: Target) -> bool:
    folded = text.casefold()
    required = (str(target.year), target.make.casefold(), target.model.casefold())
    if not all(token in folded for token in required):
        return False
    return not any(token in folded for token in ("/used/", "used-", "pre-owned", "certified"))


def discover_from_sitemaps(
    client: HttpClient,
    root_url: str,
    target: Target,
    max_documents: int = 30,
) -> SitemapResult:
    queue = deque((url, 0) for url in sitemap_seeds(client, root_url))
    visited: set[str] = set()
    candidates: list[str] = []
    errors: list[str] = []
    searched = False

    while queue and len(visited) < max_documents:
        url, depth = queue.popleft()
        if url in visited or depth > 2:
            continue
        visited.add(url)
        try:
            response = client.fetch(url, accept="application/xml,text/xml,*/*")
        except FetchError as exc:
            errors.append(f"{url}: {exc}")
            continue
        try:
            root = etree.fromstring(response.text.encode("utf-8"), parser=etree.XMLParser(recover=True))
        except (etree.XMLSyntaxError, ValueError) as exc:
            errors.append(f"{url}: invalid XML ({exc})")
            continue

        local_name = etree.QName(root).localname.casefold()
        if local_name == "sitemapindex":
            children: list[tuple[int, str]] = []
            for node in root.xpath("//*[local-name()='sitemap']"):
                locs = node.xpath("./*[local-name()='loc']/text()")
                if locs:
                    child = str(locs[0]).strip()
                    children.append((sitemap_child_score(child), child))
            preferred = [(score, child) for score, child in children if score > 0]
            if not preferred:
                preferred = sorted(children, reverse=True)[:12]
            for _, child in sorted(preferred, reverse=True)[:20]:
                if child not in visited:
                    queue.append((child, depth + 1))
            continue

        if local_name != "urlset":
            continue
        url_nodes = root.xpath("//*[local-name()='url']")
        urlset_text = " ".join(
            str(value) for node in url_nodes[:20] for value in node.xpath(".//text()")
        ).casefold()
        vehicle_like = sitemap_child_score(url) >= 80 or any(
            token in urlset_text for token in ("/new/", "new-vehicle", "vehicle-details", "/vdp/")
        )
        searched = searched or vehicle_like
        for node in url_nodes:
            locs = node.xpath("./*[local-name()='loc']/text()")
            if not locs:
                continue
            loc = str(locs[0]).strip()
            entry_text = " ".join(str(value) for value in node.xpath(".//text()"))
            if target_entry(f"{loc} {entry_text}", target):
                candidates.append(loc)

    return SitemapResult(
        candidate_urls=list(dict.fromkeys(candidates)),
        searched=searched,
        documents_checked=len(visited),
        errors=errors[-8:],
    )
