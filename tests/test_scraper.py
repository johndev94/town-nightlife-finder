import unittest

from app.scraper import extract_events, is_supported_source, scrape_url


JSON_LD_HTML = """
<html>
  <head>
    <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "Event",
        "name": "Karaoke Night",
        "startDate": "2026-04-18T20:00:00+01:00",
        "endDate": "2026-04-18T23:30:00+01:00",
        "description": "Open mic and drinks deals.",
        "offers": {"price": "5", "priceCurrency": "GBP"}
      }
    </script>
  </head>
  <body></body>
</html>
"""


HEURISTIC_HTML = """
<html>
  <body>
    <section class="event-card">
      <h3>Quiz Night</h3>
      <p>Join us for Quiz Night. Free entry and prizes. 2026-04-19T19:00:00 until 2026-04-19T21:30:00.</p>
    </section>
  </body>
</html>
"""


class ScraperTests(unittest.TestCase):
    def test_extracts_json_ld_event(self):
        events = extract_events(JSON_LD_HTML, "https://example.com/events")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Karaoke Night")
        self.assertEqual(events[0].price_label, "£5")

    def test_extracts_heuristic_event(self):
        events = extract_events(HEURISTIC_HTML, "https://example.com/whats-on")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Quiz Night")
        self.assertEqual(events[0].start_at, "2026-04-19T19:00")

    def test_marks_social_sources_unsupported(self):
        result = scrape_url("https://instagram.com/example", html="<html></html>")
        self.assertEqual(result.status, "unsupported")
        self.assertFalse(result.events)
        self.assertFalse(is_supported_source("https://facebook.com/example"))


if __name__ == "__main__":
    unittest.main()
