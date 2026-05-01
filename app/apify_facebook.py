from __future__ import annotations

import re
from io import BytesIO
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - optional dependency
    Image = None
    ImageOps = None

try:
    import pytesseract
except ImportError:  # pragma: no cover - optional dependency
    pytesseract = None


APIFY_FACEBOOK_POSTS_ACTOR = "apify~facebook-posts-scraper"
APIFY_BASE_URL = "https://api.apify.com/v2"
IMAGE_URL_PATTERN = re.compile(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", re.I)

EVENT_KEYWORDS = (
    "acoustic",
    "band",
    "bingo",
    "comedy",
    "dj",
    "gig",
    "karaoke",
    "live",
    "music",
    "open mic",
    "party",
    "quiz",
    "session",
    "show",
    "fundraiser",
    "fundraising",
    "tickets",
    "trad",
    "tasting",
)
SPORTS_ONLY_HINTS = (
    " v ",
    " vs ",
    " ireland v ",
    " giveaway",
    "voucher",
    "back ireland",
    "draw on the night",
)
NIGHTLIFE_BIAS_HINTS = (
    "tonight",
    "night",
    "dj",
    "live",
    "music",
    "party",
    "quiz",
    "karaoke",
    "bingo",
    "session",
)
MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}
TIME_PATTERN = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
PRICE_PATTERN = re.compile(r"(€\s?\d+(?:\.\d{1,2})?|eur\s?\d+(?:\.\d{1,2})?|free entry|free)", re.I)


@dataclass
class FacebookPostEvent:
    title: str
    description: str
    genre: str
    start_at: str
    end_at: str
    price_label: str
    price_amount: float | None
    source_url: str | None
    confidence: float
    post_text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_facebook_posts_scraper(
    token: str,
    page_url: str,
    results_limit: int = 20,
    newer_than: str = "3 months",
    timeout: int = 120,
) -> list[dict[str, Any]]:
    if not token:
        raise ValueError("APIFY_API_TOKEN is required.")

    endpoint = f"{APIFY_BASE_URL}/acts/{APIFY_FACEBOOK_POSTS_ACTOR}/run-sync-get-dataset-items"
    response = requests.post(
        endpoint,
        params={"token": token},
        json={
            "startUrls": [{"url": page_url}],
            "resultsLimit": results_limit,
            "onlyPostsNewerThan": newer_than,
            "captionText": False,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def extract_events_from_posts(posts: list[dict[str, Any]], venue_name: str, reference_date: datetime | None = None) -> list[FacebookPostEvent]:
    reference = reference_date or datetime.now(UTC)
    events: list[FacebookPostEvent] = []
    seen: set[tuple[str, str]] = set()

    for post in posts:
        text = post_text(post, include_ocr=True)
        if not looks_like_event(text):
            continue

        start_at = infer_start_at(text, post, reference)
        if start_at is None:
            continue

        title = infer_title(text, venue_name)
        price_label, price_amount = infer_price(text)
        genre = infer_genre(text)
        key = (title.lower(), start_at)
        if key in seen:
            continue
        seen.add(key)

        start = datetime.fromisoformat(start_at)
        end = start + timedelta(hours=3)
        events.append(
            FacebookPostEvent(
                title=title,
                description=build_event_description(post)[:500],
                genre=genre,
                start_at=start.isoformat(timespec="minutes"),
                end_at=end.isoformat(timespec="minutes"),
                price_label=price_label or "TBC",
                price_amount=price_amount,
                source_url=post_url(post),
                confidence=0.78 if price_label else 0.7,
                post_text=normalize_display_text(text),
            )
        )

    return events


def post_text(post: dict[str, Any], include_ocr: bool = False) -> str:
    parts = []
    for key in ("text", "postText", "message", "caption", "title", "description"):
        value = post.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    if include_ocr:
        ocr_text = extract_post_image_text(post)
        if ocr_text:
            parts.append(ocr_text)
    return clean_text(" ".join(parts))


def caption_text(post: dict[str, Any]) -> str:
    parts = []
    for key in ("text", "postText", "message", "caption", "title", "description"):
        value = post.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    return clean_text(" ".join(parts))


def build_event_description(post: dict[str, Any]) -> str:
    caption = normalize_display_text(caption_text(post))
    ocr_text = normalize_display_text(select_relevant_ocr_text(extract_post_image_text(post)))
    parts = [part for part in (caption, ocr_text) if part]
    if not parts:
        return ""
    if len(parts) == 2 and parts[1].lower() in parts[0].lower():
        return parts[0]
    return ". ".join(parts)


def post_url(post: dict[str, Any]) -> str | None:
    for key in ("url", "postUrl", "facebookUrl", "link"):
        value = post.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None


def extract_post_image_text(post: dict[str, Any], max_images: int = 3) -> str:
    if not ocr_is_available():
        return ""

    parts: list[str] = []
    for image_url in collect_post_image_urls(post)[:max_images]:
        text = ocr_image_url(image_url)
        if text:
            parts.append(text)
    return clean_text(" ".join(parts))


def ocr_is_available() -> bool:
    return Image is not None and ImageOps is not None and pytesseract is not None and tesseract_binary_available()


def tesseract_binary_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # pragma: no cover - environment-specific
        return False


def ocr_image_url(image_url: str, timeout: int = 20) -> str:
    if not ocr_is_available():
        return ""
    try:
        response = requests.get(image_url, timeout=timeout)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content))
        grayscale = ImageOps.grayscale(image)
        enlarged = grayscale.resize((grayscale.width * 2, grayscale.height * 2))
        enhanced = ImageOps.autocontrast(enlarged)
        text = pytesseract.image_to_string(enhanced, config="--psm 6")
        return clean_text(text or "")
    except Exception:
        return ""


def select_relevant_ocr_text(text: str) -> str:
    if not text:
        return ""
    candidates = re.split(r"(?<=[.!?])\s+|\s{2,}", text)
    kept = [
        chunk
        for chunk in candidates
        if has_event_detail(chunk)
    ]
    return clean_text(" ".join(kept[:4])) if kept else clean_text(text[:220])


def has_event_detail(text: str) -> bool:
    lowered = text.lower()
    detail_hints = (
        "tonight",
        "from",
        "starts",
        "time",
        "tickets",
        "eur",
        "dj",
        "bingo",
        "quiz",
        "karaoke",
        "music",
        "fundraising",
        "fundraiser",
    )
    return (
        any(hint in lowered for hint in detail_hints)
        or re.search(r"\b\d{1,2}[:.]\d{2}\b", text) is not None
        or re.search(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lowered) is not None
        or re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|april)\b", lowered) is not None
    )


def collect_post_image_urls(post: dict[str, Any]) -> list[str]:
    urls: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            if value.startswith("http") and IMAGE_URL_PATTERN.search(value):
                urls.append(value)
            return
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                lowered = nested_key.lower()
                if lowered in {"image", "imageurl", "image_url", "src", "url", "thumbnail"}:
                    walk(nested_value)
                elif lowered in {"images", "media", "photos", "attachments", "album", "cover", "preview"}:
                    walk(nested_value)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)

    for key in ("images", "imageUrls", "media", "mediaItems", "photos", "attachments", "pagePhotos", "image"):
        if key in post:
            walk(post[key])
    return list(dict.fromkeys(urls))


def looks_like_event(text: str) -> bool:
    lowered = text.lower()
    has_signal = any(keyword in lowered for keyword in EVENT_KEYWORDS) or has_regular_night_pattern(lowered)
    if len(text) < 20 or not has_signal:
        return False
    if is_probably_sports_promo(lowered):
        return False
    return True


def has_regular_night_pattern(lowered: str) -> bool:
    has_night_label = re.search(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+night\b", lowered) is not None
    has_time = re.search(r"\b(?:tonight\s+from|from|at)\s*\d{1,2}(?::|\.)?\d{0,2}", lowered) is not None
    return has_night_label and has_time


def is_probably_sports_promo(lowered: str) -> bool:
    if any(keyword in lowered for keyword in ("dj", "karaoke", "quiz", "bingo", "comedy", "trad", "music")):
        return False
    return any(hint in lowered for hint in SPORTS_ONLY_HINTS)


def infer_title(text: str, venue_name: str) -> str:
    first_line = clean_text(re.split(r"[\n.!?]", text, maxsplit=1)[0])
    if 3 <= len(first_line.split()) <= 9 and any(keyword in first_line.lower() for keyword in EVENT_KEYWORDS):
        return first_line[:80]

    lowered = text.lower()
    if "fundraiser" in lowered or "fundraising" in lowered:
        return f"Fundraiser at {venue_name}"
    if "quiz" in lowered:
        return f"Quiz night at {venue_name}"
    if "bingo" in lowered:
        return f"Bingo night at {venue_name}"
    if "karaoke" in lowered:
        return f"Karaoke at {venue_name}"
    if "dj" in lowered:
        return f"DJ night at {venue_name}"
    if "comedy" in lowered:
        return f"Comedy night at {venue_name}"
    if "tasting" in lowered:
        return f"Tasting event at {venue_name}"
    return f"Live music at {venue_name}"


def infer_genre(text: str) -> str:
    lowered = text.lower()
    if "quiz" in lowered:
        return "Quiz"
    if "bingo" in lowered:
        return "Special Event"
    if "fundraiser" in lowered or "fundraising" in lowered:
        return "Special Event"
    if "karaoke" in lowered:
        return "Karaoke"
    if "comedy" in lowered or "show" in lowered:
        return "Comedy"
    if "dj" in lowered or "party" in lowered or "club" in lowered:
        return "Dance"
    if "tasting" in lowered or "food" in lowered or "cocktail" in lowered:
        return "Food & Drink"
    if "trad" in lowered or "session" in lowered:
        return "Trad Music"
    return "Live Music"


def infer_price(text: str) -> tuple[str | None, float | None]:
    match = PRICE_PATTERN.search(text)
    if not match:
        return None, None
    label = clean_text(match.group(0))
    if label.lower().startswith("free"):
        return label, 0
    amount_match = re.search(r"\d+(?:\.\d{1,2})?", label)
    return label, float(amount_match.group(0)) if amount_match else None


def infer_start_at(text: str, post: dict[str, Any], reference: datetime) -> str | None:
    base_reference = post_datetime(post) or reference
    explicit = infer_day_month_datetime(text, base_reference)
    if explicit:
        return explicit

    relative = infer_relative_datetime(text, post, base_reference)
    if relative:
        return relative

    weekday = infer_weekday_datetime(text, base_reference)
    if weekday:
        return weekday

    return None


def infer_day_month_datetime(text: str, reference: datetime) -> str | None:
    match = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+("
        + "|".join(MONTHS)
        + r")(?:\s+(\d{4}))?(?:.*?\b(?:at|from)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?)?",
        text,
        re.I,
    )
    if match:
        day = int(match.group(1))
        month = MONTHS[match.group(2).lower()]
        year = int(match.group(3)) if match.group(3) else reference.year
        hour, minute = normalize_time(match.group(4), match.group(5), match.group(6), nightlife_bias=nightlife_bias(text))
        candidate = datetime(year, month, day, hour, minute)
        if candidate.date() < reference.date() and not match.group(3):
            candidate = datetime(year + 1, month, day, hour, minute)
        return local_iso(candidate)

    match = re.search(
        r"\b("
        + "|".join(MONTHS)
        + r")\s*(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?(?:.*?\b(?:time|at|from)?\s*(\d{1,2})(?::|\.)?(\d{2})?\s*(am|pm)?)?",
        text,
        re.I,
    )
    if match:
        month = MONTHS[match.group(1).lower()]
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else reference.year
        hour, minute = normalize_time(match.group(4), match.group(5), match.group(6), nightlife_bias=nightlife_bias(text))
        candidate = datetime(year, month, day, hour, minute)
        if candidate.date() < reference.date() and not match.group(3):
            candidate = datetime(year + 1, month, day, hour, minute)
        return local_iso(candidate)

    match = re.search(
        r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?:.*?\b(?:time|at|from|starts?(?:\s+at)?|kick(?:s)?\s+off(?:\s+at)?)\s*(\d{1,2})(?::|\.)?(\d{2})?\s*(am|pm)?)?",
        text,
        re.I,
    )
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))
        if year < 100:
            year += 2000
        hour, minute = normalize_time(match.group(4), match.group(5), match.group(6), nightlife_bias=nightlife_bias(text))
        candidate = datetime(year, month, day, hour, minute)
        return local_iso(candidate)

    return None


def infer_relative_datetime(text: str, post: dict[str, Any], reference: datetime) -> str | None:
    lowered = text.lower()
    base = post_datetime(post) or reference
    if "tonight" in lowered:
        hour, minute = first_time(text, default_hour=21, nightlife_bias=nightlife_bias(text))
        return local_iso(base.replace(hour=hour, minute=minute, second=0, microsecond=0))
    if "tomorrow" in lowered:
        hour, minute = first_time(text, default_hour=21, nightlife_bias=nightlife_bias(text))
        return local_iso((base + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0))
    return None


def infer_weekday_datetime(text: str, reference: datetime) -> str | None:
    lowered = text.lower()
    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", lowered):
            days_ahead = (weekday - reference.weekday()) % 7
            candidate = reference + timedelta(days=days_ahead)
            hour, minute = first_time(text, default_hour=21, nightlife_bias=nightlife_bias(text))
            return local_iso(candidate.replace(hour=hour, minute=minute, second=0, microsecond=0))
    return None


def post_datetime(post: dict[str, Any]) -> datetime | None:
    for key in ("time", "timestamp", "date", "createdAt", "creationTime"):
        value = post.get(key)
        if not value:
            continue
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, UTC)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
    return None


def first_time(text: str, default_hour: int = 21, nightlife_bias: bool = False) -> tuple[int, int]:
    contextual_patterns = (
        r"(?:from|at|starts?(?:\s+at)?|kick(?:s)?\s+off(?:\s+at)?)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?",
        r"\b(\d{1,2})(?:[:.](\d{2}))\s*(am|pm)\b",
        r"\b(\d{1,2})\s*(am|pm)\b",
    )
    for pattern in contextual_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            groups = [group for group in match.groups() if group is not None]
            if len(groups) == 3:
                return normalize_time(groups[0], groups[1], groups[2], nightlife_bias=nightlife_bias)
            if len(groups) == 2 and groups[1].lower() in {"am", "pm"}:
                return normalize_time(groups[0], None, groups[1], nightlife_bias=nightlife_bias)
    match = TIME_PATTERN.search(text)
    if not match:
        return default_hour, 0
    return normalize_time(match.group(1), match.group(2), match.group(3), nightlife_bias=nightlife_bias)


def normalize_time(hour_text: str | None, minute_text: str | None, meridiem: str | None, nightlife_bias: bool = False) -> tuple[int, int]:
    if hour_text is None:
        return 21, 0
    hour = int(hour_text)
    minute = int(minute_text or 0)
    if hour > 23 or minute > 59:
        return 21, 0
    if meridiem:
        marker = meridiem.lower()
        if marker == "pm" and hour < 12:
            hour += 12
        if marker == "am" and hour == 12:
            hour = 0
    elif nightlife_bias and 1 <= hour <= 11:
        hour += 12
    elif 1 <= hour <= 7:
        hour += 12
    return hour, minute


def nightlife_bias(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in NIGHTLIFE_BIAS_HINTS)


def local_iso(value: datetime) -> str:
    return value.replace(tzinfo=None).isoformat(timespec="minutes")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_display_text(text: str) -> str:
    if not text:
        return ""
    normalized = text.replace("â‚¬", "EUR ").replace("€", "EUR ")
    normalized = normalized.replace("“", '"').replace("”", '"').replace("’", "'")
    normalized = re.sub(r"#\w+", " ", normalized)
    normalized = re.sub(r"[|_~`]+", " ", normalized)
    normalized = re.sub(r"([A-Za-z])(\d)", r"\1 \2", normalized)
    normalized = re.sub(r"(\d)([A-Za-z])", r"\1 \2", normalized)
    normalized = re.sub(r"\b([A-Za-z]+)of\b", r"\1 of", normalized, flags=re.I)
    normalized = re.sub(r"\bCotand\b", "Cot and", normalized, flags=re.I)
    normalized = re.sub(r"\bNighttever\b", "Night Ever", normalized, flags=re.I)
    normalized = re.sub(r"\bMonbay\b", "Monday", normalized, flags=re.I)
    normalized = re.sub(r"\s+", " ", normalized).strip(" .,-")
    words = []
    for raw_word in normalized.split():
        prefix = re.match(r"^[^A-Za-z0-9]*", raw_word).group(0)
        suffix = re.search(r"[^A-Za-z0-9:.'/-]*$", raw_word).group(0)
        core = raw_word[len(prefix) : len(raw_word) - len(suffix) if suffix else len(raw_word)]
        words.append(prefix + normalize_word_case(core) + suffix)
    normalized = " ".join(words)
    normalized = re.sub(r"([.,!?=*])\1+", r"\1", normalized)
    normalized = re.sub(r"\bPER\b", "per", normalized)
    normalized = re.sub(r"\bON\b", "on", normalized)
    normalized = re.sub(r"\bALL\b", "all", normalized)
    normalized = re.sub(r"\s+([.,!?])", r"\1", normalized)
    return normalized.strip()


def normalize_word_case(word: str) -> str:
    if not word:
        return word
    upper_tokens = {"DJ", "AM", "PM", "EUR"}
    if word.upper() in upper_tokens:
        return word.upper()
    if re.fullmatch(r"\d{1,2}[:.]\d{2}", word):
        return word
    if re.fullmatch(r"\d+s", word.lower()):
        return word.upper()
    letters = [char for char in word if char.isalpha()]
    if not letters:
        return word
    upper_count = sum(1 for char in letters if char.isupper())
    lower_count = sum(1 for char in letters if char.islower())
    if upper_count >= 2 and lower_count >= 1:
        return word.title()
    if word.isupper() and len(word) > 3:
        return word.title()
    return word
