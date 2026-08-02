import json
import tempfile
import unittest
from pathlib import Path

from odyssey_watch.models import Dealer, DealerResult, Vehicle
from odyssey_watch.report import build_reports
from odyssey_watch.state import update_state


class StateReportTests(unittest.TestCase):
    def test_subset_run_preserves_unchecked_dealers(self):
        checked = Dealer("checked", "Checked Honda", "Seattle", "https://checked.example/")
        previous = {
            "schema_version": 1,
            "dealers": {"other": {"id": "other", "status": "ok"}},
            "vehicles": {
                "5FNRL6H90TB045451": {
                    "dealer_id": "other",
                    "dealer_name": "Other Honda",
                    "vin": "5FNRL6H90TB045451",
                    "verified_current": True,
                }
            },
        }
        result = DealerResult(dealer=checked, status="ok", vehicles=[])
        state = update_state(previous, [result], "2026-08-01T14:00:00Z", stale_after_hours=30)
        self.assertIn("5FNRL6H90TB045451", state["vehicles"])
        self.assertIn("other", state["dealers"])

    def test_failed_dealer_keeps_prior_vehicle_as_unverified(self):
        dealer = Dealer("sample", "Sample Honda", "Seattle", "https://dealer.example/")
        previous = {
            "schema_version": 1,
            "generated_at": "2026-07-31T14:00:00Z",
            "dealers": {},
            "vehicles": {
                "5FNRL6H90TB045451": {
                    "dealer_id": "sample",
                    "dealer_name": "Sample Honda",
                    "dealer_city": "Seattle",
                    "vin": "5FNRL6H90TB045451",
                    "url": "https://dealer.example/vdp",
                    "last_seen": "2026-07-31T14:00:00Z",
                    "first_seen": "2026-07-30T14:00:00Z",
                    "verified_current": True,
                }
            },
        }
        result = DealerResult(dealer=dealer, status="failed", checked_at="2026-08-01T14:00:00Z")
        state = update_state(previous, [result], "2026-08-01T14:00:00Z", stale_after_hours=30)
        kept = state["vehicles"]["5FNRL6H90TB045451"]
        self.assertFalse(kept["verified_current"])
        self.assertEqual(kept["stale_hours"], 24.0)
        self.assertFalse(kept["stale"])

    def test_report_artifacts(self):
        dealer = Dealer("sample", "Sample Honda", "Seattle", "https://dealer.example/")
        vehicle = Vehicle(
            dealer_id="sample",
            dealer_name="Sample Honda",
            dealer_city="Seattle",
            url="https://dealer.example/vdp",
            vin="5FNRL6H90TB045451",
            year=2026,
            make="Honda",
            model="Odyssey",
            trim="Elite",
            advertised_price=50995,
            exterior="Platinum White Pearl",
            is_white=True,
        )
        result = DealerResult(dealer=dealer, status="ok", vehicles=[vehicle])
        state = update_state(
            {"schema_version": 1, "dealers": {}, "vehicles": {}},
            [result],
            "2026-08-01T14:00:00Z",
            stale_after_hours=30,
        )
        with tempfile.TemporaryDirectory() as directory:
            build_reports(directory, state)
            root = Path(directory)
            self.assertTrue((root / "index.html").exists())
            self.assertIn("Platinum White Pearl", (root / "index.html").read_text())
            self.assertIn("advertised_price", (root / "inventory.csv").read_text())
            public = json.loads((root / "inventory.json").read_text())
            self.assertEqual(len(public["vehicles"]), 1)


if __name__ == "__main__":
    unittest.main()
