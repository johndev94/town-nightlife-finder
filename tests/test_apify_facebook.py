from datetime import UTC, datetime
import unittest
from unittest.mock import patch

from app.apify_facebook import collect_post_image_urls, extract_events_from_posts, looks_like_event, normalize_display_text, ocr_image_url, post_text, run_facebook_posts_scraper


class ApifyFacebookTestCase(unittest.TestCase):
    def test_extracts_dated_event_from_post_text(self):
        posts = [
            {
                "text": "Live music this Friday 9pm with free entry all night.",
                "url": "https://facebook.com/example/posts/1",
                "time": "2026-05-01T10:00:00+00:00",
            }
        ]

        events = extract_events_from_posts(posts, "Rouse's Bar", reference_date=datetime(2026, 5, 1, tzinfo=UTC))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].genre, "Live Music")
        self.assertEqual(events[0].price_amount, 0)
        self.assertEqual(events[0].start_at, "2026-05-01T21:00")

    def test_nightlife_time_bias_treats_tonight_1030_as_evening(self):
        posts = [
            {
                "text": "Saturday night classics DJ tonight from 10:30",
                "url": "https://facebook.com/example/posts/2",
                "time": "2026-04-25T18:00:00+00:00",
            }
        ]

        events = extract_events_from_posts(posts, "Hogan's", reference_date=datetime(2026, 4, 25, tzinfo=UTC))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].start_at, "2026-04-25T22:30")

    def test_regular_weeknight_post_with_ocr_time_becomes_event(self):
        posts = [
            {
                "text": "Wednesday Night at Hogans",
                "url": "https://facebook.com/example/posts/3",
                "time": "2026-04-29T19:42:15.000Z",
            }
        ]

        with patch("app.apify_facebook.extract_post_image_text", return_value="JOANNE GALLAGHER TONIGHT FROM 9:30"):
            events = extract_events_from_posts(posts, "Hogan's Cocktail Bar", reference_date=datetime(2026, 4, 29, tzinfo=UTC))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].start_at, "2026-04-29T21:30")

    def test_skips_event_like_post_without_date(self):
        posts = [{"text": "Live music and great drinks every weekend at the bar."}]

        events = extract_events_from_posts(posts, "Example Bar", reference_date=datetime(2026, 5, 1, tzinfo=UTC))

        self.assertEqual(events, [])

    def test_sports_promo_is_not_treated_as_event(self):
        text = "Thursday Night Ireland v Czechia giveaway EUR100 voucher draw on the night"

        self.assertFalse(looks_like_event(text))

    def test_month_first_flyer_date_is_parsed(self):
        posts = [
            {
                "text": "Fundraising for the Lourdes invalid fund",
                "url": "https://facebook.com/example/posts/4",
                "time": "2026-04-10T09:45:56.000Z",
            }
        ]

        flyer_text = "FRIDAY, APRIL 10 TIME 8PM ALL WELCOME"
        with patch("app.apify_facebook.extract_post_image_text", return_value=flyer_text):
            events = extract_events_from_posts(posts, "The Cot and Cobble", reference_date=datetime(2026, 4, 10, tzinfo=UTC))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].start_at, "2026-04-10T20:00")
        self.assertEqual(events[0].genre, "Special Event")
        self.assertEqual(events[0].title, "Fundraiser at The Cot and Cobble")
        self.assertIn("Fundraising for the Lourdes invalid fund", events[0].description)

    def test_display_text_is_normalized_for_debug_and_event_output(self):
        text = "BESTBINGO NiGHTTEVER #LoveBallina TICKETS €10 Cotand Tableof4 Monbay"

        normalized = normalize_display_text(text)

        self.assertEqual(normalized, "Bestbingo Night Ever Tickets EUR 10 Cot and Table of 4 Monday")

    @patch("app.apify_facebook.requests.get")
    def test_ocr_image_fetch_failure_returns_empty_text(self, mock_get):
        mock_get.side_effect = RuntimeError("temporary fetch failure")

        text = ocr_image_url("https://cdn.example.com/flyer.jpg")

        self.assertEqual(text, "")

    def test_collects_image_urls_from_nested_post_media(self):
        post = {
            "media": [
                {"image": {"url": "https://cdn.example.com/flyer.jpg"}},
                {"image": {"url": "https://cdn.example.com/second.png"}},
            ]
        }

        urls = collect_post_image_urls(post)

        self.assertEqual(
            urls,
            ["https://cdn.example.com/flyer.jpg", "https://cdn.example.com/second.png"],
        )

    @patch("app.apify_facebook.extract_post_image_text")
    def test_post_text_can_merge_ocr_text(self, mock_extract_post_image_text):
        mock_extract_post_image_text.return_value = "Friday 9pm free entry"

        text = post_text({"text": "Live music this week"}, include_ocr=True)

        self.assertIn("Live music this week", text)
        self.assertIn("Friday 9pm free entry", text)

    @patch("app.apify_facebook.requests.post")
    def test_run_facebook_posts_scraper_uses_apify_sync_endpoint(self, mock_post):
        class MockResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return [{"text": "Quiz night Friday 8pm"}]

        mock_post.return_value = MockResponse()

        payload = run_facebook_posts_scraper("token", "https://www.facebook.com/example/", results_limit=5, newer_than="1 month")

        self.assertEqual(payload, [{"text": "Quiz night Friday 8pm"}])
        args, kwargs = mock_post.call_args
        self.assertIn("apify~facebook-posts-scraper/run-sync-get-dataset-items", args[0])
        self.assertEqual(kwargs["params"]["token"], "token")
        self.assertEqual(kwargs["json"]["resultsLimit"], 5)
        self.assertEqual(kwargs["json"]["onlyPostsNewerThan"], "1 month")


if __name__ == "__main__":
    unittest.main()
