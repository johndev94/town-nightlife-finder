import os
import unittest
from unittest.mock import patch

from app.ai_event_cleaner import clean_event_with_ai, cleanup_models, parse_response_json


class AiEventCleanerTestCase(unittest.TestCase):
    def test_parse_response_json_reads_output_text(self):
        payload = {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"title":"Bingo night","description":"Clean copy","genre":"Special Event","price_label":"TBC","price_amount":null,"confidence":0.8,"needs_review":false,"review_reason":""}',
                        }
                    ]
                }
            ]
        }

        parsed = parse_response_json(payload)

        self.assertEqual(parsed["title"], "Bingo night")

    @patch.dict(os.environ, {"OPENAI_EVENT_CLEANUP_MODEL": "custom-model,gpt-4.1-mini"}, clear=False)
    def test_cleanup_models_preserves_configured_order_and_defaults(self):
        models = cleanup_models()

        self.assertEqual(models[0], "custom-model")
        self.assertEqual(models.count("gpt-4.1-mini"), 1)
        self.assertIn("gpt-4o-mini", models)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
    @patch("app.ai_event_cleaner.requests.post")
    def test_clean_event_with_ai_calls_responses_api_with_schema_and_image(self, mock_post):
        class MockResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": '{"title":"Fundraiser at The Cot and Cobble","description":"Fundraiser for the Killala Diocesan Lourdes Invalid Fund. EUR 40 per table of 4.","genre":"Special Event","price_label":"EUR 40","price_amount":40,"confidence":0.88,"needs_review":false,"review_reason":""}',
                                }
                            ]
                        }
                    ]
                }

        mock_post.return_value = MockResponse()

        cleaned = clean_event_with_ai(
            {"title": "Live music at The Cot and Cobble", "description": "messy OCR"},
            "The Cot and Cobble",
            "messy OCR",
            image_url="https://cdn.example.com/flyer.jpg",
        )

        self.assertEqual(cleaned.title, "Fundraiser at The Cot and Cobble")
        args, kwargs = mock_post.call_args
        self.assertIn("/v1/responses", args[0])
        self.assertEqual(kwargs["json"]["text"]["format"]["type"], "json_schema")
        image_parts = kwargs["json"]["input"][1]["content"]
        self.assertIn({"type": "input_image", "image_url": "https://cdn.example.com/flyer.jpg"}, image_parts)


if __name__ == "__main__":
    unittest.main()
