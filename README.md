# Washington Odyssey Elite inventory watch

This project checks the websites of all 27 Washington Honda franchises once each morning and builds a price-sorted report for **new 2026 Honda Odyssey Elite** vehicles. Platinum White Pearl is recognized as white and can be filtered with one checkbox.

The report keeps these distinctions explicit:

- dealer-advertised price versus MSRP;
- in-stock versus in-transit, ordered, reserved, or unstated availability;
- a verified zero versus a dealership that could not be fully checked;
- today's confirmed listings versus yesterday's unverified carryovers after a site failure.

It reads the dealership's vehicle sitemap first, then the dealer's own inventory page, and finally individual dealer vehicle pages. It does not use Honda's inventory search, Cars.com, or another inventory aggregator.

## Fastest setup: GitHub Actions + a private or public report

1. Create an empty GitHub repository and put the contents of this folder at its root. Preserve the `.github` folder.
2. In **Settings → Actions → General → Workflow permissions**, allow **Read and write permissions**. The daily workflow needs this only to commit the refreshed report and state back to the repository.
3. Open **Actions → Daily Odyssey inventory → Run workflow** for the first run. It usually takes several minutes because Chromium checks sites whose inventory is rendered by JavaScript.
4. Open `docs/index.html` from the repository after the run, or publish the friendlier web view: **Settings → Pages → Deploy from a branch → `main` → `/docs`**.

The included schedule is 6:17 a.m. every day in `America/Los_Angeles`, including daylight-saving changes. Edit `.github/workflows/daily-inventory.yml` to change it. GitHub also emails the repository owner when a run fails badly enough that fewer than 15% of dealers could be checked.

GitHub Pages visibility depends on the repository and GitHub plan. The generated report contains only public dealer inventory and no personal information.

## Run it on a computer

Python 3.12 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m playwright install chromium
python -m unittest discover -s tests -v
odyssey-watch
```

Open `docs/index.html` in a browser. The CSV and JSON exports are next to it.

Useful commands:

```bash
# Recheck one dealer while repairing or testing it
odyssey-watch --dealer klein

# Rebuild the HTML and CSV without visiting any dealer
odyssey-watch --render-only

# Standards-only mode, useful on a machine where Chromium cannot be installed
odyssey-watch --no-browser
```

## What “price” means

The default sort uses a dealer-advertised/sale/internet price when one can be identified. Otherwise it uses MSRP and labels the row accordingly. A listing with no trustworthy price sorts last.

This is not an out-the-door comparison. A dealer's number may include conditional incentives or omit installed accessories, a Washington documentation fee, taxes, and registration. Use the listing link and ask for a written, VIN-specific out-the-door quote before relying on the ranking.

## Dealer maintenance

`dealers.json` is the source of truth. Each dealer has a stable id, name, city, and canonical website. If automatic inventory-page discovery stops working for one site, add one or more direct URLs:

```json
{
  "id": "example-honda",
  "name": "Example Honda",
  "city": "Example",
  "url": "https://www.examplehonda.com/",
  "inventory_urls": [
    "https://www.examplehonda.com/new-vehicles/odyssey/"
  ]
}
```

The report's **Dealer coverage** section identifies the dealer, method, timestamp, pages checked, and the most recent warning. One dealer changing platforms will not erase results from the other 26.

The tracker honors `robots.txt`, uses a low request rate, avoids images and video, and makes no attempt to solve CAPTCHAs or evade dealer protections. If a site disallows or blocks automated access, the correct fix is an allowed inventory URL or dealer feed, not bypassing the restriction.

## Data files

- `data/state.json`: current state plus last-known listings retained only when a dealer check is partial or failed.
- `docs/index.html`: self-contained interactive report.
- `docs/inventory.csv`: spreadsheet-friendly export.
- `docs/inventory.json`: machine-readable report and dealer health data.

The VIN is the primary deduplication key. If a dealer omits the VIN, the tracker falls back to dealer + stock number + URL and marks parsing confidence lower.

