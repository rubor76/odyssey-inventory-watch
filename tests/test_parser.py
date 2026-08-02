import unittest

from odyssey_watch.models import Dealer, Target
from odyssey_watch.parser import extract_candidate_links, parse_inventory_html


TARGET = Target(
    year=2026,
    make="Honda",
    model="Odyssey",
    trim="Elite",
    preferred_colors=("Platinum White Pearl", "White"),
)
DEALER = Dealer(
    id="sample",
    name="Sample Honda",
    city="Seattle",
    url="https://dealer.example/",
)


class ParserTests(unittest.TestCase):
    def test_json_ld_vehicle(self):
        source = """
        <html><head><script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Vehicle",
          "name": "New 2026 Honda Odyssey Elite",
          "vehicleModelDate": "2026",
          "brand": {"@type":"Brand", "name":"Honda"},
          "model": "Odyssey",
          "vehicleConfiguration": "Elite",
          "vehicleIdentificationNumber": "5FNRL6H90TB045451",
          "sku": "H26001",
          "color": "Platinum White Pearl",
          "vehicleInteriorColor": "Brown",
          "vehicleCondition": "https://schema.org/NewCondition",
          "msrp": "53190",
          "offers": {"@type":"Offer", "price":"50995", "availability":"https://schema.org/InStock"},
          "url": "/new/2026-honda-odyssey-elite-5fnrl6h90tb045451/"
        }
        </script></head></html>
        """
        vehicles = parse_inventory_html(source, DEALER.url, DEALER, TARGET)
        self.assertEqual(len(vehicles), 1)
        vehicle = vehicles[0]
        self.assertEqual(vehicle.vin, "5FNRL6H90TB045451")
        self.assertEqual(vehicle.advertised_price, 50995)
        self.assertEqual(vehicle.msrp, 53190)
        self.assertTrue(vehicle.is_white)
        self.assertEqual(vehicle.condition, "New")
        self.assertEqual(
            vehicle.url,
            "https://dealer.example/new/2026-honda-odyssey-elite-5fnrl6h90tb045451/",
        )

    def test_visible_inventory_card(self):
        source = """
        <article class="vehicle-card">
          <h2>New 2026 Honda Odyssey Elite</h2>
          <div>Exterior Color: Platinum White Pearl</div>
          <div>Interior Color: Brown</div>
          <div>Stock #: H9922</div>
          <div>VIN: 5FNRL6H91TB083190</div>
          <div>MSRP: $53,190</div>
          <div>Dealer Price: $50,777</div>
          <div>In Transit</div>
          <a href="/new/vehicle/5FNRL6H91TB083190">View Details</a>
        </article>
        """
        vehicles = parse_inventory_html(source, DEALER.url, DEALER, TARGET)
        self.assertEqual(len(vehicles), 1)
        vehicle = vehicles[0]
        self.assertEqual(vehicle.stock, "H9922")
        self.assertEqual(vehicle.advertised_price, 50777)
        self.assertEqual(vehicle.msrp, 53190)
        self.assertEqual(vehicle.availability, "In transit")

    def test_used_vehicle_is_rejected(self):
        source = """
        <article><h2>Used 2026 Honda Odyssey Elite</h2>
        <div>VIN: 5FNRL6H9XTB006723</div><div>Price: $48,170</div></article>
        """
        self.assertEqual(parse_inventory_html(source, DEALER.url, DEALER, TARGET), [])

    def test_candidate_links(self):
        source = """
        <div><a href="/new/2026-honda-odyssey-elite/abc">2026 Honda Odyssey Elite</a></div>
        <div><a href="/used/2026-honda-odyssey-elite/xyz">Used 2026 Honda Odyssey Elite</a></div>
        """
        links = extract_candidate_links(source, DEALER.url, TARGET)
        self.assertEqual(links, ["https://dealer.example/new/2026-honda-odyssey-elite/abc"])


if __name__ == "__main__":
    unittest.main()

