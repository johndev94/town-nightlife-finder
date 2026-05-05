from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODELS = ("gpt-4.1-mini", "gpt-4o-mini", "gpt-5-mini")

EVENT_CLEANUP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "genre": {"type": "string"},
        "price_label": {"type": "string"},
        "price_amount": {"type": ["number", "null"]},
        "confidence": {"type": "number"},
        "needs_review": {"type": "boolean"},
        "review_reason": {"type": "string"},
    },
    "required": [
        "title",
        "description",
        "genre",
        "price_label",
        "price_amount",
        "confidence",
        "needs_review",
        "review_reason",
    ],
}


@dataclass
class CleanedEventFields:
    title: str
    description: str
    genre: str
    price_label: str
    price_amount: float | None
    confidence: float
    needs_review: bool
    review_reason: str


def ai_cleanup_enabled() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def clean_event_with_ai(
    event_payload: dict[str, Any],
    venue_name: str,
    raw_text: str,
    image_url: str | None = None,
    timeout: int = 45,
) -> CleanedEventFields | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": json.dumps(
                {
                    "venue_name": venue_name,
                    "raw_text": raw_text,
                    "current_event": event_payload,
                    "rules": [
                        "Polish casing, spelling, and OCR noise.",
                        "Keep the event factual. Do not invent performers, prices, dates, or times.",
                        "Use EUR prices when clear. Use TBC when price is unclear.",
                        "Keep the description under 220 characters and suitable for a public nightlife listing.",
                        "Set needs_review true when details are uncertain or OCR quality is poor.",
                    ],
                },
                ensure_ascii=True,
            ),
        }
    ]
    if image_url:
        content.append({"type": "input_image", "image_url": image_url})

    payload = {
        "input": [
            {
                "role": "system",
                "content": (
                    "You clean imported nightlife event listings. Return concise, natural, "
                    "factual event copy. Preserve uncertainty instead of guessing."
                ),
            },
            {"role": "user", "content": content},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "event_cleanup",
                "schema": EVENT_CLEANUP_SCHEMA,
                "strict": True,
            }
        },
    }

    response = None
    last_error: requests.HTTPError | None = None
    for model in cleanup_models():
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={**payload, "model": model},
            timeout=timeout,
        )
        try:
            response.raise_for_status()
            last_error = None
            break
        except requests.HTTPError as exc:
            last_error = exc
            if response.status_code not in {404, 400}:
                raise enriched_http_error(exc)

    if last_error is not None:
        raise enriched_http_error(last_error)
    if response is None:
        return None

    parsed = parse_response_json(response.json())
    if parsed is None:
        return None
    return CleanedEventFields(
        title=parsed["title"].strip()[:120],
        description=parsed["description"].strip()[:500],
        genre=parsed["genre"].strip()[:60],
        price_label=parsed["price_label"].strip()[:40] or "TBC",
        price_amount=parsed["price_amount"],
        confidence=max(0.0, min(1.0, float(parsed["confidence"]))),
        needs_review=bool(parsed["needs_review"]),
        review_reason=parsed["review_reason"].strip()[:180],
    )


def cleanup_models() -> list[str]:
    configured = os.environ.get("OPENAI_EVENT_CLEANUP_MODEL", "").strip()
    models = [model.strip() for model in configured.split(",") if model.strip()]
    for model in DEFAULT_MODELS:
        if model not in models:
            models.append(model)
    return models


def enriched_http_error(exc: requests.HTTPError) -> requests.HTTPError:
    response = exc.response
    if response is None:
        return exc
    try:
        detail = response.json()
    except ValueError:
        detail = response.text[:500]
    message = f"{exc} | OpenAI response: {detail}"
    return requests.HTTPError(message, response=response)


def parse_response_json(payload: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(payload.get("output_text"), str):
        return json.loads(payload["output_text"])

    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                return json.loads(content["text"])
    return None
