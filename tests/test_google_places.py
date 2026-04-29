import os
import tempfile
import unittest

from app import create_app
from app.db import get_db, init_db
from app.google_places import (
    VenueCandidate,
    VenueCorrection,
    address_contains_required_location,
    apply_correction,
    apply_manual_location,
    build_venue_queries,
    candidate_from_place,
    ensure_google_place_columns,
    find_best_candidate,
)


class GooglePlacesCorrectionTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test", "DATABASE": self.db_path})
        self.context = self.app.app_context()
        self.context.push()
        init_db()

    def tearDown(self):
        self.context.pop()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_candidate_from_place_extracts_google_location(self):
        venue = {"name": "Bar Square Ballina", "area_name": "Ballina Town"}
        place = {
            "id": "google-place-123",
            "displayName": {"text": "Bar Square"},
            "formattedAddress": "Garden Street, Ballina, Co. Mayo, Ireland",
            "location": {"latitude": 54.11495, "longitude": -9.15387},
            "googleMapsUri": "https://maps.google.com/?cid=123",
            "businessStatus": "OPERATIONAL",
        }

        candidate = candidate_from_place(venue, place, "Bar Square Ballina, Ballina, Ireland")

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.place_id, "google-place-123")
        self.assertEqual(candidate.latitude, 54.11495)
        self.assertGreater(candidate.score, 0.5)
        self.assertEqual(candidate.matched_query, "Bar Square Ballina, Ballina, Ireland")

    def test_required_location_rejects_wrong_town(self):
        self.assertTrue(address_contains_required_location("Garden Street, Ballina, Co. Mayo, Ireland", "Ballina Town"))
        self.assertFalse(address_contains_required_location("Main Street, Dublin, Ireland", "Ballina Town"))

    def test_build_venue_queries_creates_fallback_queries(self):
        venue = {
            "name": "Bar Square Ballina",
            "address": "Garden Street, Ballina, Co. Mayo, Ireland",
            "area_name": "Ballina Town",
        }

        queries = build_venue_queries(venue)

        self.assertIn("Bar Square Ballina, Ballina, Co. Mayo, Ireland", queries)
        self.assertIn("Bar Square Ballina, Ballina, Ireland", queries)
        self.assertEqual(queries[-1], "Bar Square Ballina")

    def test_find_best_candidate_tries_fallback_queries(self):
        class FakeClient:
            def __init__(self) -> None:
                self.queries: list[str] = []

            def search_text(self, query: str) -> list[dict[str, object]]:
                self.queries.append(query)
                if query == "Bar Square Ballina, Ballina, Ireland":
                    return [
                        {
                            "id": "google-place-123",
                            "displayName": {"text": "Bar Square"},
                            "formattedAddress": "Garden Street, Ballina, Co. Mayo, Ireland",
                            "location": {"latitude": 54.11495, "longitude": -9.15387},
                            "googleMapsUri": "https://maps.google.com/?cid=123",
                            "businessStatus": "OPERATIONAL",
                        }
                    ]
                return []

        venue = {
            "id": 99,
            "name": "Bar Square Ballina",
            "slug": "bar-square-ballina",
            "address": "Garden Street, Ballina, Co. Mayo, Ireland",
            "latitude": 54.114658,
            "longitude": -9.157807,
            "area_name": "Ballina Town",
        }

        client = FakeClient()
        correction = find_best_candidate(client, venue)

        self.assertIsNotNone(correction.candidate)
        self.assertEqual(correction.candidate.place_id, "google-place-123")
        self.assertEqual(correction.query, "Bar Square Ballina, Ballina, Ireland")
        self.assertGreater(len(client.queries), 1)

    def test_apply_correction_updates_venue_and_source(self):
        db = get_db()
        ensure_google_place_columns(db)
        venue = db.execute("SELECT * FROM venues WHERE slug = 'the-lantern-arms'").fetchone()
        correction = VenueCorrection(
            venue_id=venue["id"],
            venue_name=venue["name"],
            slug=venue["slug"],
            current_address=venue["address"],
            current_latitude=venue["latitude"],
            current_longitude=venue["longitude"],
            query="The Lantern Arms, 12 Market Row",
            candidate=VenueCandidate(
                place_id="google-place-456",
                name="The Lantern Arms",
                address="12 Market Row, Test Town",
                latitude=53.95123,
                longitude=-1.08123,
                google_maps_uri="https://maps.google.com/?cid=456",
                business_status="OPERATIONAL",
                score=0.91,
                matched_query="The Lantern Arms, 12 Market Row",
            ),
        )

        apply_correction(db, correction)
        db.commit()

        updated = db.execute("SELECT * FROM venues WHERE id = ?", (venue["id"],)).fetchone()
        self.assertEqual(updated["google_place_id"], "google-place-456")
        self.assertEqual(updated["address"], "12 Market Row, Test Town")
        self.assertEqual(updated["latitude"], 53.95123)
        self.assertEqual(updated["sync_status"], "google-verified")

        source = db.execute(
            "SELECT * FROM sources WHERE entity_type = 'venue' AND entity_id = ? AND platform = 'Google Places'",
            (venue["id"],),
        ).fetchone()
        self.assertIsNotNone(source)
        self.assertEqual(source["confidence"], 0.91)

    def test_manual_location_override_updates_coordinates(self):
        db = get_db()
        updated = apply_manual_location(
            db,
            "the-lantern-arms",
            53.95,
            -1.08,
            address="Manual Test Address",
        )
        db.commit()

        self.assertTrue(updated)
        venue = db.execute("SELECT * FROM venues WHERE slug = 'the-lantern-arms'").fetchone()
        self.assertEqual(venue["latitude"], 53.95)
        self.assertEqual(venue["longitude"], -1.08)
        self.assertEqual(venue["address"], "Manual Test Address")
        self.assertEqual(venue["sync_status"], "manual-location")


if __name__ == "__main__":
    unittest.main()
