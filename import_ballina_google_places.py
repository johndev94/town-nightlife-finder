from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app import create_app
from app.db import get_db
from app.google_places import GooglePlacesClient, load_env_file


BALLINA_QUERY_SET = [
    ("bars in Ballina, Co. Mayo, Ireland", "Bar"),
    ("pubs in Ballina, Co. Mayo, Ireland", "Pub"),
    ("nightclubs in Ballina, Co. Mayo, Ireland", "Nightclub"),
]


@dataclass(frozen=True)
class ImportedPlace:
    place_id: str
    name: str
    address: str
    latitude: float
    longitude: float
    google_maps_uri: str | None
    inferred_type: str
    source_query: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Ballina pubs/bars/nightclubs from Google Places into the venue map.")
    parser.add_argument("--apply", action="store_true", help="Write changes to the database. Default is dry-run.")
    return parser.parse_args()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    slug = slug.replace("-co-mayo", "")
    return slug


def normalise_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def is_ballina_result(address: str) -> bool:
    normalised = normalise_text(address)
    return "ballina" in normalised and "mayo" in normalised


def infer_type(name: str, default_type: str) -> str:
    lowered = name.lower()
    if "nightclub" in lowered or "club" in lowered or "quay west" in lowered:
        return "Nightclub"
    if "pub" in lowered:
        return "Pub"
    if "cocktail" in lowered or "bar" in lowered or "loft" in lowered:
        return "Bar"
    return default_type


def should_import_place(name: str) -> bool:
    lowered = name.lower()
    nightlife_keywords = ("bar", "pub", "club", "nightclub", "cocktail", "loft", "monk")
    if any(keyword in lowered for keyword in nightlife_keywords):
        return True
    non_nightlife_only = ("kitchen", "bistro", "cafe", "restaurant", "hotel")
    if any(keyword in lowered for keyword in non_nightlife_only):
        return False
    return True


def collect_ballina_places(client: GooglePlacesClient) -> list[ImportedPlace]:
    collected: dict[str, ImportedPlace] = {}
    for query, default_type in BALLINA_QUERY_SET:
        places = client.search_text(query)
        for place in places:
            place_id = place.get("id")
            location = place.get("location") or {}
            name = (place.get("displayName") or {}).get("text") or ""
            address = place.get("formattedAddress") or ""
            latitude = location.get("latitude")
            longitude = location.get("longitude")
            if not place_id or not name or latitude is None or longitude is None:
                continue
            if not is_ballina_result(address):
                continue
            if not should_import_place(name):
                continue
            imported = ImportedPlace(
                place_id=place_id,
                name=name,
                address=address,
                latitude=float(latitude),
                longitude=float(longitude),
                google_maps_uri=place.get("googleMapsUri"),
                inferred_type=infer_type(name, default_type),
                source_query=query,
            )
            existing = collected.get(place_id)
            if existing is None:
                collected[place_id] = imported
            elif existing.inferred_type == "Bar" and imported.inferred_type in {"Pub", "Nightclub"}:
                collected[place_id] = imported
    return sorted(collected.values(), key=lambda item: item.name.lower())


def fetch_ballina_area(db: Any) -> Any:
    area = db.execute("SELECT * FROM areas WHERE slug = 'ballina-town'").fetchone()
    if area is None:
        raise SystemExit("Ballina area was not found. Run seed_ballina.py first.")
    return area


def upsert_place(db: Any, area_id: int, place: ImportedPlace) -> str:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    slug = slugify(place.name)
    existing = db.execute(
        "SELECT id, slug, description, price_band, opens_at, closes_at, social_website FROM venues WHERE google_place_id = ? OR slug = ?",
        (place.place_id, slug),
    ).fetchone()

    description = (
        existing["description"]
        if existing and existing["description"]
        else f"Imported from Google Places for Ballina map coverage. Opening hours, pricing, and events still need review."
    )
    price_band = existing["price_band"] if existing and existing["price_band"] else "TBC"
    opens_at = existing["opens_at"] if existing and existing["opens_at"] else "TBC"
    closes_at = existing["closes_at"] if existing and existing["closes_at"] else "TBC"
    social_website = existing["social_website"] if existing and existing["social_website"] else None

    if existing:
        db.execute(
            """
            UPDATE venues
            SET area_id = ?, name = ?, venue_type = ?, address = ?, description = ?, price_band = ?,
                latitude = ?, longitude = ?, opens_at = ?, closes_at = ?, social_website = ?,
                google_place_id = ?, google_maps_uri = ?, is_published = 1, source_type = ?,
                source_url = ?, sync_status = ?, confidence = ?, last_verified_at = ?
            WHERE id = ?
            """,
            (
                area_id,
                place.name,
                place.inferred_type,
                place.address,
                description,
                price_band,
                place.latitude,
                place.longitude,
                opens_at,
                closes_at,
                social_website,
                place.place_id,
                place.google_maps_uri,
                "external-reference",
                place.google_maps_uri,
                "needs-review",
                0.7,
                now,
                existing["id"],
            ),
        )
        venue_id = existing["id"]
        action = "updated"
    else:
        venue_id = db.execute(
            """
            INSERT INTO venues
            (
                area_id, name, slug, venue_type, address, description, price_band, latitude, longitude,
                opens_at, closes_at, social_facebook, social_instagram, social_website, google_place_id,
                google_maps_uri, is_published, source_type, source_url, sync_status, confidence, last_verified_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                area_id,
                place.name,
                slug,
                place.inferred_type,
                place.address,
                description,
                price_band,
                place.latitude,
                place.longitude,
                opens_at,
                closes_at,
                social_website,
                place.place_id,
                place.google_maps_uri,
                "external-reference",
                place.google_maps_uri,
                "needs-review",
                0.7,
                now,
            ),
        ).lastrowid
        action = "inserted"

    db.execute(
        """
        INSERT INTO sources
        (entity_type, entity_id, platform, source_type, source_url, sync_status, confidence, last_verified_at, notes)
        VALUES ('venue', ?, 'Google Places', 'external-reference', ?, 'needs-review', 0.7, ?, ?)
        """,
        (
            venue_id,
            place.google_maps_uri,
            now,
            f"Imported from Google Places query: {place.source_query}",
        ),
    )
    return action


def main() -> None:
    args = parse_args()
    load_env_file()
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing GOOGLE_MAPS_API_KEY in .env")

    client = GooglePlacesClient(api_key)
    places = collect_ballina_places(client)
    if not places:
        print("No Ballina venues were returned by Google Places.")
        return

    app = create_app()
    inserted = 0
    updated = 0
    with app.app_context():
        db = get_db()
        area = fetch_ballina_area(db)
        print(f"Found {len(places)} Ballina Google Places result(s). Mode: {'apply' if args.apply else 'dry-run'}")
        for place in places:
            print(f"- {place.name} | {place.inferred_type} | {place.address}")
            if args.apply:
                action = upsert_place(db, area["id"], place)
                if action == "inserted":
                    inserted += 1
                else:
                    updated += 1
        if args.apply:
            db.commit()

    if args.apply:
        print(f"\nApplied changes. Inserted {inserted}, updated {updated}.")
    else:
        print("\nDry-run only. Re-run with --apply to write these venues into the Ballina map.")


if __name__ == "__main__":
    main()
