import os
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from app.db import ADMIN_PASSWORD, get_db, init_db


class NightlifeFinderTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test", "DATABASE": self.db_path})
        self.client = self.app.test_client()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def login(self, username, password):
        return self.client.post("/login", data={"username": username, "password": password}, follow_redirects=True)

    def test_area_filter_limits_venues(self):
        response = self.client.get("/api/venues?area=old-town")
        self.assertEqual(response.status_code, 200)
        self.assertEqual({venue["name"] for venue in response.get_json()}, {"The Lantern Arms", "Velvet Room"})

    def test_genre_filter_limits_events(self):
        response = self.client.get("/api/events?genre=Karaoke&date=2026-04-01")
        events = response.get_json()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"], "Karaoke Night")

    def test_unpublished_events_are_hidden(self):
        response = self.client.get("/api/events")
        self.assertNotIn("Student Social", {event["title"] for event in response.get_json()})

    def test_event_detail_api_includes_coordinates(self):
        response = self.client.get("/api/events/1")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["title"], "Karaoke Night")
        self.assertIn("coordinates", payload["venue"])
        self.assertIn("lat", payload["venue"]["coordinates"])
        self.assertIn("image_url", payload)

    def test_event_detail_api_includes_image_url(self):
        with self.app.app_context():
            init_db()
            get_db().execute("UPDATE events SET image_url = ? WHERE id = 1", ("https://cdn.example.com/flyer.jpg",))
            get_db().commit()

        response = self.client.get("/api/events/1")

        self.assertEqual(response.get_json()["image_url"], "https://cdn.example.com/flyer.jpg")

    def test_event_page_route_exists(self):
        response = self.client.get("/events/1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("app-root", response.get_data(as_text=True))

    def test_bounds_filter_limits_map_results(self):
        response = self.client.get("/api/venues?bounds_north=53.959&bounds_south=53.957&bounds_east=-1.080&bounds_west=-1.083")
        venues = response.get_json()
        self.assertEqual(len(venues), 1)
        self.assertEqual(venues[0]["slug"], "the-lantern-arms")

    @unittest.skip("Owner accounts have been removed; only the admin login is available.")
    def test_owner_can_update_claimed_venue_only(self):
        self.login("velvet_owner", "ownerpass")
        response = self.client.post(
            "/dashboard/venues/2",
            data={"opens_at": "21:00", "closes_at": "03:30", "price_band": "£££", "source_type": "owner", "source_url": "https://velvetroom.example.com", "sync_status": "owner-updated", "confidence": "0.88"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/venues/velvet-room").get_json()["opens_at"], "21:00")

        forbidden = self.client.post(
            "/dashboard/venues/1",
            data={"opens_at": "21:00", "closes_at": "01:00", "price_band": "££", "source_type": "owner", "source_url": "", "sync_status": "owner-updated", "confidence": "0.7"},
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_claim_submission_creates_pending_request(self):
        response = self.client.post(
            "/claims",
            data={"venue_id": "1", "claimant_name": "Alex Harper", "claimant_email": "alex@example.com", "message": "Please let us update karaoke times."},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Claim request submitted", response.get_data(as_text=True))

    def test_only_admin_login_is_available(self):
        old_admin = self.login("admin", "adminpass")
        self.assertIn("Invalid username or password.", old_admin.get_data(as_text=True))

        owner = self.login("velvet_owner", "ownerpass")
        self.assertIn("Invalid username or password.", owner.get_data(as_text=True))

        admin = self.login("admin", ADMIN_PASSWORD)
        self.assertIn("Admin dashboard", admin.get_data(as_text=True))

        with self.app.app_context():
            users = get_db().execute("SELECT username FROM users ORDER BY username").fetchall()
            self.assertEqual([user["username"] for user in users], ["admin"])

    def test_admin_can_review_claim(self):
        self.login("admin", ADMIN_PASSWORD)
        response = self.client.post("/dashboard/claims/1", data={"status": "approved"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("approved.", response.get_data(as_text=True))

    def test_admin_can_reject_claim_and_remove_it_from_pending_list(self):
        self.login("admin", ADMIN_PASSWORD)
        response = self.client.post("/dashboard/claims/1", data={"status": "rejected"}, follow_redirects=True)
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("rejected.", body)
        self.assertIn("No claim requests are waiting for review.", body)

    def test_admin_bulk_unpublish_venues_redirects_to_draft_pubs(self):
        self.login("admin", ADMIN_PASSWORD)
        response = self.client.post(
            "/dashboard/admin-tools/bulk-venue-action",
            data={"venue_ids": ["1"], "bulk_action": "unpublish", "queue": "all"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/dashboard?queue=draft-pubs#review-queue")
        with self.app.app_context():
            row = get_db().execute("SELECT is_published FROM venues WHERE id = 1").fetchone()
            self.assertEqual(row["is_published"], 0)

    def test_admin_bulk_unpublish_events_redirects_to_draft_events(self):
        self.login("admin", ADMIN_PASSWORD)
        response = self.client.post(
            "/dashboard/admin-tools/bulk-event-action",
            data={"event_ids": ["1"], "bulk_action": "unpublish", "queue": "all"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/dashboard?queue=draft-events#review-queue")
        with self.app.app_context():
            row = get_db().execute("SELECT is_published FROM events WHERE id = 1").fetchone()
            self.assertEqual(row["is_published"], 0)

    @patch("app.views.requests.get")
    def test_route_api_returns_osrm_geometry(self, mock_get):
        class MockResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "routes": [
                        {
                            "distance": 1200.0,
                            "duration": 840.0,
                            "geometry": {
                                "coordinates": [
                                    [-9.1536, 54.1159],
                                    [-9.151, 54.1165],
                                ]
                            },
                        }
                    ]
                }

        mock_get.return_value = MockResponse()

        response = self.client.post(
            "/api/route",
            json={
                "from": {"lat": 54.1159, "lng": -9.1536},
                "to": {"lat": 54.1165, "lng": -9.1510},
                "mode": "walking",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["provider"], "osrm")
        self.assertEqual(len(payload["geometry"]), 2)
        self.assertEqual(payload["geometry"][0]["lat"], 54.1159)


if __name__ == "__main__":
    unittest.main()
