from __future__ import annotations

import os
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


def build_venue_query(venue: Any) -> str:
    pieces = [
        venue["name"],
        venue["address"],
        venue["area_name"],
    ]
    if "Ireland" not in " ".join(pieces):
        pieces.append("Ireland")
    return ", ".join(piece for piece in pieces if piece)


def score_place(venue_name: str, area_name: str, place: dict[str, Any]) -> float:
    display_name = (place.get("displayName") or {}).get("text") or ""
    address = place.get("formattedAddress") or ""
    name_score = SequenceMatcher(None, venue_name.lower(), display_name.lower()).ratio()
    area_score = 0.12 if area_name.lower().replace(" town", "") in address.lower() else 0
    open_score = 0.08 if place.get("businessStatus") != "CLOSED_PERMANENTLY" else -0.35
    return round(min(1.0, max(0.0, name_score + area_score + open_score)), 3)


def candidate_from_place(venue: Any, place: dict[str, Any]) -> VenueCandidate | None:
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
    )


def find_best_candidate(client: GooglePlacesClient, venue: Any) -> VenueCorrection:
    query = build_venue_query(venue)
    try:
        places = client.search_text(query)
    except requests.RequestException as exc:
        return VenueCorrection(
            venue_id=venue["id"],
            venue_name=venue["name"],
            slug=venue["slug"],
            current_address=venue["address"],
            current_latitude=venue["latitude"],
            current_longitude=venue["longitude"],
            candidate=None,
            query=query,
            error=str(exc),
        )

    candidates = [candidate for place in places if (candidate := candidate_from_place(venue, place))]
    best = max(candidates, key=lambda candidate: candidate.score, default=None)
    return VenueCorrection(
        venue_id=venue["id"],
        venue_name=venue["name"],
        slug=venue["slug"],
        current_address=venue["address"],
        current_latitude=venue["latitude"],
        current_longitude=venue["longitude"],
        candidate=best,
        query=query,
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


def rate_limit_pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
