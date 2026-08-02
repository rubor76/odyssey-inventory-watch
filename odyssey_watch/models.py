from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Target:
    year: int
    make: str
    model: str
    trim: str
    preferred_colors: tuple[str, ...] = ()


@dataclass(frozen=True)
class Dealer:
    id: str
    name: str
    city: str
    url: str
    inventory_urls: tuple[str, ...] = ()
    enabled: bool = True


@dataclass
class Vehicle:
    dealer_id: str
    dealer_name: str
    dealer_city: str
    url: str
    vin: str | None = None
    stock: str | None = None
    year: int | None = None
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    exterior: str | None = None
    interior: str | None = None
    advertised_price: int | None = None
    msrp: int | None = None
    price_label: str | None = None
    price_notes: str | None = None
    availability: str | None = None
    condition: str | None = None
    source: str = "dealer website"
    checked_at: str | None = None
    first_seen: str | None = None
    last_seen: str | None = None
    is_white: bool = False
    verified_current: bool = True
    parser_confidence: str = "medium"
    evidence: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        if self.vin:
            return self.vin.upper()
        fallback = "|".join(
            str(value or "").lower()
            for value in (self.dealer_id, self.stock, self.url)
        )
        return fallback

    @property
    def sort_price(self) -> int | None:
        return self.advertised_price if self.advertised_price is not None else self.msrp

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sort_price"] = self.sort_price
        return data


@dataclass
class DealerResult:
    dealer: Dealer
    status: str
    vehicles: list[Vehicle] = field(default_factory=list)
    checked_at: str | None = None
    method: str | None = None
    message: str | None = None
    pages_checked: int = 0
    candidate_urls: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.dealer.id,
            "name": self.dealer.name,
            "city": self.dealer.city,
            "url": self.dealer.url,
            "status": self.status,
            "checked_at": self.checked_at,
            "method": self.method,
            "message": self.message,
            "pages_checked": self.pages_checked,
            "candidate_urls": self.candidate_urls,
            "vehicle_count": len(self.vehicles),
        }

