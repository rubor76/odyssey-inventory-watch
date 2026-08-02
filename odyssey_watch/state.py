from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import DealerResult, Vehicle


def load_state(path: str | Path) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        return {"schema_version": 1, "generated_at": None, "dealers": {}, "vehicles": {}}
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError(f"Unsupported state schema: {raw.get('schema_version')}")
    raw.setdefault("dealers", {})
    raw.setdefault("vehicles", {})
    return raw


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(state_path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(state_path)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def update_state(
    previous: dict[str, Any],
    results: list[DealerResult],
    generated_at: str,
    stale_after_hours: int,
) -> dict[str, Any]:
    previous_vehicles: dict[str, dict[str, Any]] = previous.get("vehicles", {})
    checked_dealer_ids = {result.dealer.id for result in results}
    vehicles: dict[str, dict[str, Any]] = {
        key: dict(value)
        for key, value in previous_vehicles.items()
        if value.get("dealer_id") not in checked_dealer_ids
    }
    dealers: dict[str, dict[str, Any]] = dict(previous.get("dealers", {}))
    now = _parse_time(generated_at) or datetime.now(UTC)

    for result in results:
        dealers[result.dealer.id] = result.to_dict()
        current_keys: set[str] = set()
        for vehicle in result.vehicles:
            key = vehicle.key
            prior = previous_vehicles.get(key, {})
            vehicle.first_seen = prior.get("first_seen") or generated_at
            vehicle.last_seen = generated_at
            vehicle.checked_at = generated_at
            vehicle.verified_current = True
            vehicles[key] = vehicle.to_dict()
            current_keys.add(key)

        if result.status != "ok":
            for key, prior in previous_vehicles.items():
                if prior.get("dealer_id") != result.dealer.id or key in current_keys:
                    continue
                stale = dict(prior)
                stale["verified_current"] = False
                last_seen = _parse_time(stale.get("last_seen"))
                age_hours = (now - last_seen).total_seconds() / 3600 if last_seen else None
                stale["stale_hours"] = round(age_hours, 1) if age_hours is not None else None
                stale["stale"] = age_hours is None or age_hours >= stale_after_hours
                vehicles[key] = stale

    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "dealers": dealers,
        "vehicles": vehicles,
    }
