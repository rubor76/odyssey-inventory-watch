from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .report import build_reports
from .scraper import InventoryScraper, utc_now
from .state import load_state, save_state, update_state


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Track Washington 2026 Honda Odyssey Elite inventory")
    command.add_argument("--config", default="dealers.json", help="Path to dealer configuration")
    command.add_argument("--state", default="data/state.json", help="Persistent state file")
    command.add_argument("--docs", default="docs", help="Output directory for HTML/CSV/JSON")
    command.add_argument("--dealer", action="append", help="Run only one dealer id (repeatable)")
    command.add_argument("--no-browser", action="store_true", help="Use HTTP/sitemaps only")
    command.add_argument("--render-only", action="store_true", help="Rebuild reports from existing state")
    command.add_argument(
        "--fail-below-coverage",
        type=float,
        default=0.15,
        help="Exit nonzero if fewer than this fraction of dealers are ok or partial",
    )
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config = load_config(args.config)
    previous = load_state(args.state)

    if args.render_only:
        build_reports(args.docs, previous)
        print(f"Reports written to {Path(args.docs).resolve()}")
        return 0

    requested = set(args.dealer) if args.dealer else None
    unknown = requested - {dealer.id for dealer in config.dealers} if requested else set()
    if unknown:
        print(f"Unknown dealer id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    scraper = InventoryScraper(config, use_browser=not args.no_browser)
    results = scraper.scrape_all(requested)
    generated_at = utc_now()
    current = update_state(
        previous,
        results,
        generated_at=generated_at,
        stale_after_hours=config.settings.stale_after_hours,
    )
    save_state(args.state, current)
    build_reports(args.docs, current)

    covered = sum(result.status in {"ok", "partial"} for result in results)
    coverage = covered / len(results) if results else 0.0
    matches = sum(len(result.vehicles) for result in results)
    print(
        f"Finished: {matches} current matches; {covered}/{len(results)} dealers checked "
        f"({coverage:.0%} coverage)"
    )
    return 1 if coverage < args.fail_below_coverage else 0


if __name__ == "__main__":
    raise SystemExit(main())

