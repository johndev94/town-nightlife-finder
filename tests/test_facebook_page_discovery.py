import unittest
from unittest.mock import patch

from app.facebook_page_discovery import (
    best_confident_candidate,
    canonicalize_facebook_page_url,
    discover_facebook_page_candidates,
    extract_facebook_candidates_from_website,
    parse_bing_rss_results,
)


class FacebookPageDiscoveryTestCase(unittest.TestCase):
    def test_parse_bing_rss_results_extracts_link_title_and_snippet(self):
        xml = """<?xml version="1.0"?>
        <rss><channel>
          <item>
            <title>Bar Square Ballina | Facebook</title>
            <link>https://www.facebook.com/barsquareballina/</link>
            <description>Ballina, Mayo</description>
          </item>
        </channel></rss>
        """

        results = parse_bing_rss_results(xml)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://www.facebook.com/barsquareballina/")
        self.assertEqual(results[0]["title"], "Bar Square Ballina | Facebook")
        self.assertEqual(results[0]["snippet"], "Ballina, Mayo")

    def test_extract_facebook_candidates_from_website_finds_social_link(self):
        html = """
        <html>
          <head><title>Bar Square | Paddy Mac's | Time Square Ballina</title></head>
          <body>
            <a href="https://www.facebook.com/barsquareballina/">Facebook</a>
          </body>
        </html>
        """

        results = extract_facebook_candidates_from_website(html, "https://www.barsquare-ballina.com/")

        self.assertEqual(results[0]["url"], "https://www.facebook.com/barsquareballina/")

    def test_canonicalize_facebook_page_url_filters_post_urls(self):
        self.assertIsNone(canonicalize_facebook_page_url("https://www.facebook.com/example/posts/123"))
        self.assertEqual(
            canonicalize_facebook_page_url("https://m.facebook.com/barsquareballina"),
            "https://www.facebook.com/barsquareballina/",
        )

    @patch("app.facebook_page_discovery.search_bing_rss")
    def test_discover_candidates_ranks_page_match_highest(self, mock_search):
        mock_search.return_value = [
            {
                "url": "https://www.facebook.com/barsquareballina/",
                "title": "Bar Square Ballina | Facebook",
                "snippet": "Garden Street, Ballina, Mayo",
            },
            {
                "url": "https://www.facebook.com/someone/posts/123",
                "title": "Bar Square poster",
                "snippet": "A post about Ballina",
            },
        ]

        candidates = discover_facebook_page_candidates("Bar Square", max_candidates=3)

        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0].url, "https://www.facebook.com/barsquareballina/")
        self.assertGreater(candidates[0].score, 0.72)

    def test_best_confident_candidate_requires_gap(self):
        class Candidate:
            def __init__(self, score):
                self.score = score

        self.assertIsNone(best_confident_candidate([Candidate(0.81), Candidate(0.77)], min_score=0.72, min_gap=0.08))
        self.assertIsNotNone(best_confident_candidate([Candidate(0.81), Candidate(0.7)], min_score=0.72, min_gap=0.08))


if __name__ == "__main__":
    unittest.main()
