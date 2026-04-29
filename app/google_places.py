from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests


GOOGLE_PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.googleMapsUri",
        "places.businessStatus",
    ]
)


def normalise_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = value.strip().strip(",")
        if not cleaned:
            continue
        key = normalise_text(cleaned)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered


def compose_query(*parts: str | None) -> str:
    pieces = dedupe_strings([part or "" for part in parts])
    joined = ", ".join(pieces)
    if joined and "ireland" not in normalise_text(joined):
        joined = f"{joined}, Ireland"
    return joined


@dataclass(frozen=True)
class VenueCandidate:
    place_id: str
    name: str
    address: str
    latitude: float
    longitude: float
    google_maps_uri: str | None
    business_status: str | None
    score: float
    matched_query: str


@dataclass(frozen=True)
class VenueCorrection:
    venue_id: int
    venue_name: str
    slug: str
    current_address: str
    current_latitude: float
    current_longitude: float
    candidate: VenueCandidate | None
    query: str
    error: str | None = None

    @property
    def can_apply(self) -> bool:
        return self.candidate is not None and self.error is None


def load_env_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


class GooglePlacesClient:
    def __init__(self, api_key: str, session: requests.Session | None = None, timeout: int = 20) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout

    def search_text(self, query: str) -> list[dict[str, Any]]:
        response = self.session.post(
            GOOGLE_PLACES_TEXT_SEARCH_URL,
            json={"textQuery": query, "regionCode": "IE", "languageCode": "en"},
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": GOOGLE_FIELD_MASK,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("places", [])


def area_town_name(area_name: str) -> str:
    return re.sub(r"\btown\b", "", area_name, flags=re.IGNORECASE).strip(" ,")


def county_from_address(address: str) -> str | None:
    match = re.search(r"\b(?:co\.?\s+)?([A-Z][a-z]+)\b(?=,\s*Ireland|\s*,?\s*Ireland|$)", address)
    if not match:
        return None
    county = match.group(1).strip()
    if county.lower() in {"ireland", "road", "street"}:
        return None
    return f"Co. {county}" if not county.lower().startswith("co") else county


def build_venue_queries(venue: Any) -> list[str]:
    name = (venue["name"] or "").strip()
    address = (venue["address"] or "").strip()
    area_name = (venue["area_name"] or "").strip()
    town_name = area_town_name(area_name)
    county = county_from_address(address)
    if county is None and "mayo" in normalise_text(address):
        county = "Co. Mayo"

    candidate_queries = [
        compose_query(name, address),
        compose_query(name, town_name, county),
        compose_query(name, town_name),
        compose_query(name, county),
        name,
    ]
    return dedupe_strings(candidate_queries)


def address_contains_required_location(address: str, area_name: str) -> bool:
    normalised_address = normalise_text(address)
    town = normalise_text(area_town_name(area_name))
    has_town = bool(town and town in normalised_address)
    has_ireland = "ireland" in normalised_address or " ie" in f" {normalised_address} "
    has_county = bool(re.search(r"\bco\s+[a-z]+\b", normalised_address))
    return has_town and (has_ireland or has_county)


def token_overlap_score(left: str, right: str) -> float:
    left_tokens = set(normalise_text(left).split())
    right_tokens = set(normalise_text(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    return overlap / max(len(left_tokens), len(right_tokens))


def score_place(venue_name: str, area_name: str, place: dict[str, Any]) -> float:
    display_name = (place.get("displayName") or {}).get("text") or ""
    address = place.get("formattedAddress") or ""
    sequence_score = SequenceMatcher(None, normalise_text(venue_name), normalise_text(display_name)).ratio()
    overlap_score = token_overlap_score(venue_name, display_name)
    name_score = max(sequence_score, overlap_score)
    location_score = 0.24 if address_contains_required_location(address, area_name) else -0.45
    open_score = 0.08 if place.get("businessStatus") != "CLOSED_PERMANENTLY" else -0.35
    return round(min(1.0, max(0.0, name_score + location_score + open_score)), 3)


def candidate_from_place(venue: Any, place: dict[str, Any], matched_query: str) -> VenueCandidate | None:
    location = place.get("location") or {}
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    place_id = place.get("id")
    if not place_id or latitude is None or longitude is None:
        return None
    return VenueCandidate(
        place_id=place_id,
        name=(place.get("displayName") or {}).get("text") or "",
        address=place.get("formattedAddress") or "",
        latitude=float(latitude),
        longitude=float(longitude),
        google_maps_uri=place.get("googleMapsUri"),
        business_status=place.get("businessStatus"),
        score=score_place(venue["name"], venue["area_name"], place),
        matched_query=matched_query,
    )


def find_best_candidate(client: GooglePlacesClient, venue: Any) -> VenueCorrection:
    queries = build_venue_queries(venue)
    collected: dict[str, VenueCandidate] = {}
    last_error: str | None = None
    had_successful_request = False

    for query in queries:
        try:
            places = client.search_text(query)
        except requests.RequestException as exc:
            last_error = str(exc)
            continue
        had_successful_request = True

        for place in places:
            address = place.get("formattedAddress") or ""
            if not address_contains_required_location(address, venue["area_name"]):
                continue
            candidate = candidate_from_place(venue, place, query)
            if candidate is None:
                continue
            current = collected.get(candidate.place_id)
            if current is None or candidate.score > current.score:
                collected[candidate.place_id] = candidate

    best = max(collected.values(), key=lambda candidate: candidate.score, default=None)
    return VenueCorrection(
        venue_id=venue["id"],
        venue_name=venue["name"],
        slug=venue["slug"],
        current_address=venue["address"],
        current_latitude=venue["latitude"],
        current_longitude=venue["longitude"],
        candidate=best,
        query=best.matched_query if best else queries[0],
        error=last_error if best is None and not had_successful_request and last_error else None,
    )


def ensure_google_place_columns(db: Any) -> None:
    columns = {row["name"] for row in db.execute("PRAGMA table_info(venues)").fetchall()}
    if "google_place_id" not in columns:
        db.execute("ALTER TABLE venues ADD COLUMN google_place_id TEXT")
    if "google_maps_uri" not in columns:
        db.execute("ALTER TABLE venues ADD COLUMN google_maps_uri TEXT")


def apply_correction(db: Any, correction: VenueCorrection, update_address: bool = True) -> None:
    if correction.candidate is None:
        return

    now = datetime.now(UTC).isoformat(timespec="seconds")
    candidate = correction.candidate
    address = candidate.address if update_address and candidate.address else correction.current_address

    db.execute(
        """
        UPDATE venues
        SET address = ?, latitude = ?, longitude = ?, google_place_id = ?, google_maps_uri = ?,
            sync_status = ?, confidence = ?, last_verified_at = ?
        WHERE id = ?
        """,
        (
            address,
            candidate.latitude,
            candidate.longitude,
            candidate.place_id,
            candidate.google_maps_uri,
            "google-verified" if candidate.score >= 0.72 else "needs-review",
            candidate.score,
            now,
            correction.venue_id,
        ),
    )
    db.execute(
        """
        INSERT INTO sources
        (entity_type, entity_id, platform, source_type, source_url, sync_status, confidence, last_verified_at, notes)
        VALUES ('venue', ?, 'Google Places', 'external-reference', ?, ?, ?, ?, ?)
        """,
        (
            correction.venue_id,
            candidate.google_maps_uri,
            "google-verified" if candidate.score >= 0.72 else "needs-review",
            candidate.score,
            now,
            f"Matched Google Place ID {candidate.place_id} from query: {correction.query}",
        ),
    )


def apply_manual_location(
    db: Any,
    slug: str,
    latitude: float,
    longitude: float,
    address: str | None = None,
    notes: str | None = None,
) -> bool:
    venue = db.execute("SELECT id, address FROM venues WHERE slug = ?", (slug,)).fetchone()
    if venue is None:
        return False

    now = datetime.now(UTC).isoformat(timespec="seconds")
    db.execute(
        """
        UPDATE venues
        SET address = ?, latitude = ?, longitude = ?, sync_status = ?, confidence = ?, last_verified_at = ?
        WHERE id = ?
        """,
        (address or venue["address"], latitude, longitude, "manual-location", 1.0, now, venue["id"]),
    )
    db.execute(
        """
        INSERT INTO sources
        (entity_type, entity_id, platform, source_type, source_url, sync_status, confidence, last_verified_at, notes)
        VALUES ('venue', ?, 'Manual location', 'manual', NULL, 'manual-location', 1.0, ?, ?)
        """,
        (venue["id"], now, notes or f"Manual coordinate override for {slug}: {latitude}, {longitude}"),
    )
    return True


def rate_limit_pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
