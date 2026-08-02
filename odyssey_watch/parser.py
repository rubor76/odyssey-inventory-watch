from __future__ import annotations

import html as html_lib
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urljoin

from lxml import html

from .models import Dealer, Target, Vehicle


VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b", re.IGNORECASE)
MONEY_RE = re.compile(r"\$\s*([1-9]\d{1,2}(?:,\d{3})+)\b")
YEAR_RE = re.compile(r"\b(20\d{2})\b")
SPACE_RE = re.compile(r"[ \t\r\f\v]+")

PRICE_LABELS: tuple[tuple[str, int], ...] = (
    ("sale price", 100),
    ("dealer price", 95),
    ("internet price", 95),
    ("eprice", 90),
    ("our price", 90),
    ("selling price", 90),
    ("special price", 85),
    ("price", 60),
)

MSRP_LABELS = ("msrp", "manufacturer suggested retail price", "retail price")
BAD_PRICE_CONTEXT = (
    "per month",
    "/month",
    "/mo",
    "monthly",
    "down payment",
    "lease for",
    "finance for",
    "savings",
    "discount",
    "rebate",
)

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "vin": ("vin", "vehicleidentificationnumber", "vehicle_id", "vehicleid"),
    "stock": ("stock", "stocknumber", "stock_number", "sku"),
    "year": ("year", "vehiclemodeldate", "modelyear", "model_year"),
    "make": ("make", "brand", "manufacturer"),
    "model": ("model", "vehiclemodel", "modelname"),
    "trim": ("trim", "trimname", "vehicleconfiguration", "style"),
    "exterior": (
        "exterior",
        "exteriorcolor",
        "exterior_color",
        "color",
        "vehiclecolor",
    ),
    "interior": ("interior", "interiorcolor", "interior_color", "vehicleinteriorcolor"),
    "condition": ("condition", "vehiclecondition", "inventorytype"),
    "availability": ("availability", "inventorystatus", "status"),
    "url": ("url", "vehicleurl", "canonicalurl", "link"),
    "name": ("name", "title", "vehiclename"),
    "price": ("price", "saleprice", "internetprice", "dealerprice", "ourprice"),
    "msrp": ("msrp", "listprice", "retailprice"),
}


def normalize_space(value: Any) -> str:
    text = html_lib.unescape(str(value or ""))
    text = SPACE_RE.sub(" ", text)
    return text.strip()


def normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]", "", str(value).lower())


def scalar(value: Any) -> Any:
    if isinstance(value, Mapping):
        for key in ("name", "value", "@value", "text", "label"):
            if key in value and not isinstance(value[key], (Mapping, list)):
                return value[key]
        return None
    if isinstance(value, list):
        for item in value:
            picked = scalar(item)
            if picked not in (None, ""):
                return picked
        return None
    return value


def lookup(data: Mapping[str, Any], field: str) -> Any:
    aliases = set(FIELD_ALIASES[field])
    for key, value in data.items():
        if normalize_key(key) in aliases:
            picked = scalar(value)
            if picked not in (None, ""):
                return picked
    return None


def money(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        amount = int(round(value))
    else:
        match = re.search(r"([1-9]\d{1,2}(?:,\d{3})+|[1-9]\d{4,5})(?:\.\d{1,2})?", str(value))
        if not match:
            return None
        amount = int(match.group(1).replace(",", ""))
    return amount if 10_000 <= amount <= 150_000 else None


def year_value(value: Any) -> int | None:
    match = YEAR_RE.search(str(value or ""))
    return int(match.group(1)) if match else None


def is_target_text(text: str, target: Target, require_trim: bool = True) -> bool:
    folded = text.casefold()
    required = (str(target.year), target.make.casefold(), target.model.casefold())
    if not all(token in folded for token in required):
        return False
    return not require_trim or target.trim.casefold() in folded


def is_white_color(color: str | None, preferred: Iterable[str]) -> bool:
    folded = (color or "").casefold()
    return "white" in folded or any(item.casefold() in folded for item in preferred)


def normalize_condition(value: Any) -> str | None:
    text = normalize_space(value)
    folded = text.casefold()
    if not text:
        return None
    if "new" in folded and not any(word in folded for word in ("used", "pre-owned", "certified")):
        return "New"
    if any(word in folded for word in ("used", "pre-owned", "certified")):
        return "Used"
    return text[:80]


def normalize_availability(value: Any) -> str | None:
    text = normalize_space(value)
    folded = text.casefold()
    if not text:
        return None
    labels = (
        ("in transit", "In transit"),
        ("coming soon", "Coming soon"),
        ("dealer ordered", "Dealer ordered"),
        ("in stock", "In stock"),
        ("available", "Available"),
        ("reserved", "Reserved"),
        ("pending", "Pending"),
        ("sold", "Sold"),
    )
    for needle, label in labels:
        if needle in folded:
            return label
    if "instock" in folded:
        return "In stock"
    if "preorder" in folded:
        return "Dealer ordered"
    return text[:80]


def mapping_text(data: Mapping[str, Any]) -> str:
    pieces: list[str] = []
    for field in ("name", "year", "make", "model", "trim", "condition", "exterior"):
        value = lookup(data, field)
        if value not in (None, ""):
            pieces.append(str(value))
    return " ".join(pieces)


def iter_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from iter_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_mappings(child)


def looks_vehicle_mapping(data: Mapping[str, Any], target: Target) -> bool:
    text = mapping_text(data)
    vin = lookup(data, "vin")
    type_text = normalize_space(data.get("@type", "")).casefold()
    typed = any(word in type_text for word in ("vehicle", "car", "product"))
    return is_target_text(text, target, require_trim=False) and (bool(vin) or typed)


def extract_offer_prices(data: Mapping[str, Any]) -> tuple[int | None, int | None, str | None]:
    advertised = money(lookup(data, "price"))
    msrp = money(lookup(data, "msrp"))
    label = "Advertised price" if advertised else None

    offers = data.get("offers") or data.get("Offers")
    for offer in iter_mappings(offers):
        candidate = money(lookup(offer, "price"))
        if candidate is not None:
            advertised = candidate
            label = "Advertised price"
            break
    return advertised, msrp, label


def vehicle_from_mapping(
    data: Mapping[str, Any],
    dealer: Dealer,
    target: Target,
    page_url: str,
) -> Vehicle | None:
    text = mapping_text(data)
    if not is_target_text(text, target, require_trim=False):
        return None

    condition = normalize_condition(lookup(data, "condition"))
    if condition == "Used":
        return None

    name = normalize_space(lookup(data, "name"))
    trim = normalize_space(lookup(data, "trim")) or None
    if not trim and target.trim.casefold() in name.casefold():
        trim = target.trim
    if (trim or "").casefold() != target.trim.casefold() and target.trim.casefold() not in name.casefold():
        return None

    raw_vin = normalize_space(lookup(data, "vin")).upper()
    vin_match = VIN_RE.search(raw_vin)
    vin = vin_match.group(1).upper() if vin_match else None
    exterior = normalize_space(lookup(data, "exterior")) or None
    advertised, msrp, price_label = extract_offer_prices(data)
    raw_url = normalize_space(lookup(data, "url")) or page_url

    return Vehicle(
        dealer_id=dealer.id,
        dealer_name=dealer.name,
        dealer_city=dealer.city,
        url=urljoin(page_url, raw_url),
        vin=vin,
        stock=normalize_space(lookup(data, "stock")) or None,
        year=year_value(lookup(data, "year") or name),
        make=normalize_space(lookup(data, "make")) or target.make,
        model=normalize_space(lookup(data, "model")) or target.model,
        trim=trim or target.trim,
        exterior=exterior,
        interior=normalize_space(lookup(data, "interior")) or None,
        advertised_price=advertised,
        msrp=msrp,
        price_label=price_label,
        availability=normalize_availability(lookup(data, "availability")),
        condition=condition or "New",
        is_white=is_white_color(exterior, target.preferred_colors),
        parser_confidence="high" if vin else "medium",
        evidence=["structured vehicle data"],
    )


def line_value(lines: list[str], labels: tuple[str, ...], max_follow: int = 2) -> str | None:
    for index, line in enumerate(lines):
        folded = line.casefold()
        for label in labels:
            pos = folded.find(label)
            if pos == -1:
                continue
            remainder = normalize_space(line[pos + len(label) :].lstrip(" :#-"))
            if remainder and remainder.casefold() not in labels:
                return remainder[:100]
            for candidate in lines[index + 1 : index + 1 + max_follow]:
                candidate = normalize_space(candidate)
                if candidate:
                    return candidate[:100]
    return None


def extract_prices_from_lines(lines: list[str]) -> tuple[int | None, int | None, str | None, str | None]:
    advertised_candidates: list[tuple[int, int, str, str]] = []
    msrp_candidates: list[int] = []
    for index, line in enumerate(lines):
        folded_line = line.casefold()
        values = [int(match.group(1).replace(",", "")) for match in MONEY_RE.finditer(line)]
        if not values and any(
            label in folded_line for label in MSRP_LABELS + tuple(item[0] for item in PRICE_LABELS)
        ):
            following = " ".join(lines[index + 1 : index + 3])
            values = [
                int(match.group(1).replace(",", ""))
                for match in MONEY_RE.finditer(following)
            ][:1]
        values = [value for value in values if 10_000 <= value <= 150_000]
        if not values:
            continue
        if any(label in folded_line for label in MSRP_LABELS):
            msrp_candidates.extend(values)
            continue
        if any(bad in folded_line for bad in BAD_PRICE_CONTEXT):
            continue
        for label, priority in PRICE_LABELS:
            if label in folded_line:
                advertised_candidates.append((priority, -index, label.title(), str(values[0])))
                break
    advertised = None
    price_label = None
    notes = None
    if advertised_candidates:
        priority, _, price_label, raw_value = max(advertised_candidates)
        del priority
        advertised = int(raw_value)
        notes = "Label copied from dealer page"
    msrp = min(msrp_candidates) if msrp_candidates else None
    if advertised is not None and msrp is not None and advertised > msrp * 1.4:
        advertised = None
        price_label = None
    return advertised, msrp, price_label, notes


def element_lines(element: Any) -> list[str]:
    lines: list[str] = []
    for text in element.itertext():
        cleaned = normalize_space(text)
        if cleaned:
            lines.append(cleaned)
    return lines


def best_vehicle_container(node: Any, target: Target) -> Any:
    current = node
    for _ in range(8):
        if current is None:
            break
        text = " ".join(element_lines(current))
        if len(text) > 12_000:
            break
        if is_target_text(text, target, require_trim=False):
            return current
        current = current.getparent()
    return node


def vehicle_from_text(
    text_lines: list[str],
    dealer: Dealer,
    target: Target,
    page_url: str,
    link_url: str | None = None,
) -> Vehicle | None:
    joined = "\n".join(text_lines)
    if not is_target_text(joined, target, require_trim=True):
        return None
    if re.search(r"\b(?:used|pre-owned|certified)\b", joined, re.IGNORECASE):
        new_pos = re.search(r"\bnew\b", joined, re.IGNORECASE)
        used_pos = re.search(r"\b(?:used|pre-owned|certified)\b", joined, re.IGNORECASE)
        if not new_pos or (used_pos and used_pos.start() < new_pos.start()):
            return None

    vin_match = VIN_RE.search(joined)
    exterior = line_value(text_lines, ("exterior color", "ext. color", "exterior"))
    interior = line_value(text_lines, ("interior color", "int. color", "interior"))
    stock = line_value(text_lines, ("stock number", "stock #", "stock:"))
    advertised, msrp, price_label, price_notes = extract_prices_from_lines(text_lines)
    availability = normalize_availability(joined)

    return Vehicle(
        dealer_id=dealer.id,
        dealer_name=dealer.name,
        dealer_city=dealer.city,
        url=urljoin(page_url, link_url or page_url),
        vin=vin_match.group(1).upper() if vin_match else None,
        stock=stock,
        year=target.year,
        make=target.make,
        model=target.model,
        trim=target.trim,
        exterior=exterior,
        interior=interior,
        advertised_price=advertised,
        msrp=msrp,
        price_label=price_label,
        price_notes=price_notes,
        availability=availability,
        condition="New",
        is_white=is_white_color(exterior, target.preferred_colors),
        parser_confidence="high" if vin_match else "low",
        evidence=["visible dealer page text"],
    )


def json_documents(tree: Any) -> Iterable[Any]:
    for script in tree.xpath("//script"):
        script_type = (script.get("type") or "").casefold()
        raw = script.text or ""
        if not raw.strip():
            continue
        if "json" not in script_type and not raw.lstrip().startswith(("{", "[")):
            continue
        try:
            yield json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue


def merge_vehicle(existing: Vehicle, incoming: Vehicle) -> Vehicle:
    for field in (
        "vin",
        "stock",
        "year",
        "make",
        "model",
        "trim",
        "exterior",
        "interior",
        "advertised_price",
        "msrp",
        "price_label",
        "price_notes",
        "availability",
        "condition",
    ):
        if getattr(existing, field) in (None, "") and getattr(incoming, field) not in (None, ""):
            setattr(existing, field, getattr(incoming, field))
    if incoming.url and (not existing.url or len(incoming.url) > len(existing.url)):
        existing.url = incoming.url
    existing.is_white = existing.is_white or incoming.is_white
    existing.evidence = sorted(set(existing.evidence + incoming.evidence))
    ranks = {"low": 0, "medium": 1, "high": 2}
    if ranks.get(incoming.parser_confidence, 0) > ranks.get(existing.parser_confidence, 0):
        existing.parser_confidence = incoming.parser_confidence
    return existing


def deduplicate(vehicles: Iterable[Vehicle]) -> list[Vehicle]:
    output: dict[str, Vehicle] = {}
    for index, vehicle in enumerate(vehicles):
        key = vehicle.key or f"row-{index}"
        if key in output:
            output[key] = merge_vehicle(output[key], vehicle)
        else:
            output[key] = vehicle
    return list(output.values())


def parse_inventory_html(source: str, page_url: str, dealer: Dealer, target: Target) -> list[Vehicle]:
    if not source.strip():
        return []
    try:
        tree = html.fromstring(source, base_url=page_url)
    except (ValueError, TypeError):
        return []

    found: list[Vehicle] = []
    for document in json_documents(tree):
        for mapping in iter_mappings(document):
            if looks_vehicle_mapping(mapping, target):
                vehicle = vehicle_from_mapping(mapping, dealer, target, page_url)
                if vehicle:
                    found.append(vehicle)

    seen_vins: set[str] = set()
    for node in tree.xpath("//*[text()]"):
        direct = normalize_space(node.text)
        vins = VIN_RE.findall(direct)
        for vin in vins:
            vin = vin.upper()
            if vin in seen_vins:
                continue
            seen_vins.add(vin)
            container = best_vehicle_container(node, target)
            lines = element_lines(container)
            links = container.xpath(".//a[@href]/@href")
            vehicle = vehicle_from_text(lines, dealer, target, page_url, links[0] if links else None)
            if vehicle:
                vehicle.vin = vin
                vehicle.parser_confidence = "high"
                found.append(vehicle)

    if not found:
        lines = element_lines(tree)
        vehicle = vehicle_from_text(lines, dealer, target, page_url)
        if vehicle:
            found.append(vehicle)

    return deduplicate(found)


def extract_candidate_links(source: str, page_url: str, target: Target) -> list[str]:
    try:
        tree = html.fromstring(source, base_url=page_url)
    except (ValueError, TypeError):
        return []
    scored: list[tuple[int, str]] = []
    for anchor in tree.xpath("//a[@href]"):
        href = urljoin(page_url, anchor.get("href"))
        text = " ".join(element_lines(anchor))
        parent_text = text
        parent = anchor.getparent()
        if parent is not None:
            parent_text = " ".join(element_lines(parent))[:1000]
        combined = f"{href} {text} {parent_text}".casefold()
        if target.model.casefold() not in combined:
            continue
        score = 0
        if str(target.year) in combined:
            score += 20
        if target.make.casefold() in combined:
            score += 10
        if target.trim.casefold() in combined:
            score += 20
        if any(token in combined for token in ("/new/", "new-vehicle", "new_inventory", "inventory")):
            score += 10
        if any(token in combined for token in ("used", "pre-owned", "certified")):
            score -= 50
        if score >= 20:
            scored.append((score, href.split("#", 1)[0]))
    return [url for _, url in sorted(set(scored), reverse=True)]


def discover_inventory_links(source: str, page_url: str, target: Target) -> list[str]:
    try:
        tree = html.fromstring(source, base_url=page_url)
    except (ValueError, TypeError):
        return []
    scored: list[tuple[int, str]] = []
    for anchor in tree.xpath("//a[@href]"):
        href = urljoin(page_url, anchor.get("href")).split("#", 1)[0]
        text = " ".join(element_lines(anchor)).casefold()
        combined = f"{text} {href.casefold()}"
        score = 0
        if target.model.casefold() in combined:
            score += 100
        if "new inventory" in combined or "all new" in combined:
            score += 80
        elif "new vehicles" in combined or "/new-" in combined or "/new_" in combined:
            score += 60
        if any(token in combined for token in ("used", "pre-owned", "certified", "service", "parts")):
            score -= 100
        if score > 0 and href.startswith(("http://", "https://")):
            scored.append((score, href))
    ordered: list[str] = []
    for _, url in sorted(scored, reverse=True):
        if url not in ordered:
            ordered.append(url)
    return ordered[:5]
