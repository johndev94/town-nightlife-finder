from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


USER_AGENT = "TownNightlifeFinderBot/0.1 (+https://localhost)"
UNSUPPORTED_HOST_MARKERS = ("facebook.com", "instagram.com", "tiktok.com", "x.com", "twitter.com")
PRICE_PATTERN = re.compile(r"(£\s?\d+(?:\.\d{1,2})?(?:\s*(?:-|to|/)\s*£?\s?\d+(?:\.\d{1,2})?)?|free entry|free)", re.I)


@dataclass
class ScrapedEvent:
    title: str
    start_at: str | None
    end_at: str | None
    description: str
    price_label: str | None
    source_url: str
    source_type: str = "website-scrape"


@dataclass
class ScrapeResult:
    source_url: str
    fetched_at: str
    status: str
    confidence: float
    platform: str
    events: list[ScrapedEvent]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "status": self.status,
            "confidence": self.confidence,
            "platform": self.platform,
            "events": [asdict(event) for event in self.events],
            "notes": self.notes,
        }


def infer_platform(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    if "instagram.com" in host:
        return "instagram"
    if "facebook.com" in host:
        return "facebook"
    if "tiktok.com" in host:
        return "tiktok"
    return "website"


def is_supported_source(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return not any(marker in host for marker in UNSUPPORTED_HOST_MARKERS)


def fetch_html(url: str, timeout: int = 15) -> str:
    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        },
    )
    response.raise_for_status()
    return response.text


def scrape_url(url: str, html: str | None = None) -> ScrapeResult:
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    platform = infer_platform(url)
    notes: list[str] = []

    if not is_supported_source(url):
        return ScrapeResult(
            source_url=url,
            fetched_at=fetched_at,
            status="unsupported",
            confidence=0.0,
            platform=platform,
            events=[],
            notes=[
                "Skipped unsupported platform source.",
                "Use official APIs or manual/admin entry for social platforms.",
            ],
        )

    try:
        document = html if html is not None else fetch_html(url)
    except requests.RequestException as exc:
        return ScrapeResult(
            source_url=url,
            fetched_at=fetched_at,
            status="error",
            confidence=0.0,
            platform=platform,
            events=[],
            notes=[f"Fetch failed: {exc}"],
        )

    events = extract_events(document, url, notes)
    confidence = 0.85 if events else 0.25
    status = "parsed" if events else "no-events-found"
    if not events:
        notes.append("No event-like content was confidently extracted.")

    return ScrapeResult(
        source_url=url,
        fetched_at=fetched_at,
        status=status,
        confidence=confidence,
        platform=platform,
        events=events,
        notes=notes,
    )


def extract_events(html: str, source_url: str, notes: list[str] | None = None) -> list[ScrapedEvent]:
    soup = BeautifulSoup(html, "html.parser")
    collected: list[ScrapedEvent] = []

    json_ld_events = extract_json_ld_events(soup, source_url)
    if json_ld_events:
        if notes is not None:
            notes.append(f"Extracted {len(json_ld_events)} event(s) from JSON-LD.")
        collected.extend(json_ld_events)

    heuristic_events = extract_heuristic_events(soup, source_url)
    if heuristic_events:
        if notes is not None:
            notes.append(f"Extracted {len(heuristic_events)} event candidate(s) from page content.")
        merge_events(collected, heuristic_events)

    return collected


def extract_json_ld_events(soup: BeautifulSoup, source_url: str) -> list[ScrapedEvent]:
    events: list[ScrapedEvent] = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in flatten_json_ld(payload):
            if not isinstance(item, dict):
                continue
            kind = item.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if "Event" not in kinds:
                continue
            title = clean_text(item.get("name"))
            if not title:
                continue
            events.append(
                ScrapedEvent(
                    title=title,
                    start_at=normalize_datetime(item.get("startDate")),
                    end_at=normalize_datetime(item.get("endDate")),
                    description=clean_text(item.get("description")) or "",
                    price_label=extract_offer_price(item.get("offers")),
                    source_url=source_url,
                )
            )
    return dedupe_events(events)


def flatten_json_ld(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        items: list[Any] = []
        for item in payload:
            items.extend(flatten_json_ld(item))
        return items
    if isinstance(payload, dict) and "@graph" in payload:
        return flatten_json_ld(payload["@graph"])
    return [payload]


def extract_heuristic_events(soup: BeautifulSoup, source_url: str) -> list[ScrapedEvent]:
    events: list[ScrapedEvent] = []
    selectors = [
        "[class*='event']",
        "[id*='event']",
        "article",
        "section",
        "li",
        ".card",
    ]
    seen_blocks: set[str] = set()
    for selector in selectors:
        for node in soup.select(selector):
            text = clean_text(node.get_text(" ", strip=True))
            if not text or len(text) < 24:
                continue
            signature = text[:120].lower()
            if signature in seen_blocks:
                continue
            seen_blocks.add(signature)

            title = clean_text(first_text(node.select_one("h1, h2, h3, h4, strong, b")))
            if not title or len(title.split()) > 10:
                continue

            if not likely_event_text(text):
                continue

            price = extract_price_label(text)
            description = text
            start_at, end_at = extract_datetimes_from_text(text)
            events.append(
                ScrapedEvent(
                    title=title,
                    start_at=start_at,
                    end_at=end_at,
                    description=description,
                    price_label=price,
                    source_url=source_url,
                )
            )
    return dedupe_events(events)


def extract_datetimes_from_text(text: str) -> tuple[str | None, str | None]:
    iso_matches = re.findall(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?", text)
    if iso_matches:
        start = normalize_datetime(iso_matches[0])
        end = normalize_datetime(iso_matches[1]) if len(iso_matches) > 1 else None
        return start, end
    return None, None


def extract_offer_price(offers: Any) -> str | None:
    if isinstance(offers, dict):
        price = offers.get("price")
        currency = offers.get("priceCurrency", "GBP")
        if price in (None, ""):
            return clean_text(offers.get("name"))
        symbol = "£" if currency == "GBP" else f"{currency} "
        return f"{symbol}{price}"
    if isinstance(offers, list):
        for offer in offers:
            price = extract_offer_price(offer)
            if price:
                return price
    return None


def extract_price_label(text: str) -> str | None:
    match = PRICE_PATTERN.search(text)
    return clean_text(match.group(0)) if match else None


def likely_event_text(text: str) -> bool:
    lowered = text.lower()
    hints = ("live", "dj", "karaoke", "quiz", "night", "event", "friday", "saturday", "tickets", "entry")
    return any(hint in lowered for hint in hints)


def merge_events(existing: list[ScrapedEvent], new_events: list[ScrapedEvent]) -> None:
    existing_keys = {(item.title.lower(), item.start_at or "") for item in existing}
    for item in new_events:
        key = (item.title.lower(), item.start_at or "")
        if key not in existing_keys:
            existing.append(item)
            existing_keys.add(key)


def dedupe_events(events: list[ScrapedEvent]) -> list[ScrapedEvent]:
    deduped: list[ScrapedEvent] = []
    seen: set[tuple[str, str]] = set()
    for item in events:
        key = (item.title.lower(), item.start_at or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def first_text(node: Any) -> str | None:
    if node is None:
        return None
    return clean_text(node.get_text(" ", strip=True))


def normalize_datetime(value: Any) -> str | None:
    if not value:
        return None
    text = clean_text(str(value))
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).isoformat(timespec="minutes")
    except ValueError:
        return text


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None
