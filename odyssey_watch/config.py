from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Dealer, Target


@dataclass(frozen=True)
class Settings:
    request_timeout_seconds: int = 25
    browser_timeout_seconds: int = 35
    pause_between_dealers_seconds: float = 1.5
    stale_after_hours: int = 30
    max_vehicle_pages_per_dealer: int = 40
    user_agent: str = "OdysseyInventoryWatch/1.0"


@dataclass(frozen=True)
class Config:
    target: Target
    settings: Settings
    dealers: tuple[Dealer, ...]


def load_config(path: str | Path) -> Config:
    raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    target_raw = raw["target"]
    target = Target(
        year=int(target_raw["year"]),
        make=str(target_raw["make"]),
        model=str(target_raw["model"]),
        trim=str(target_raw["trim"]),
        preferred_colors=tuple(target_raw.get("preferred_colors", ())),
    )
    settings = Settings(**raw.get("settings", {}))
    dealers = tuple(
        Dealer(
            id=item["id"],
            name=item["name"],
            city=item["city"],
            url=item["url"],
            inventory_urls=tuple(item.get("inventory_urls", ())),
            enabled=bool(item.get("enabled", True)),
        )
        for item in raw["dealers"]
    )
    ids = [dealer.id for dealer in dealers]
    if len(ids) != len(set(ids)):
        raise ValueError("Dealer ids must be unique")
    return Config(target=target, settings=settings, dealers=dealers)

