from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import create_app
from app.db import get_db
from app.google_places import GooglePlacesClient, ensure_google_place_columns, load_env_file


QUERY_TEMPLATES = [
    ("bars in {town}, Co. {county}, Ireland", "Bar"),
    ("pubs in {town}, Co. {county}, Ireland", "Pub"),
    ("nightclubs in {town}, Co. {county}, Ireland", "Nightclub"),
    ("cocktail bars in {town}, Co. {county}, Ireland", "Bar"),
    ("live music pubs in {town}, Co. {county}, Ireland", "Pub"),
]

IRELAND_LOCATIONS_PATH = Path("frontend/src/irelandLocations.ts")


@dataclass(frozen=True)
class ImportedPlace:
    place_id: str
    name: str
    address: str
    latitude: float
    longitude: float
    google_maps_uri: str | None
    website_uri: str | None
    inferred_type: str
    source_query: str
    place_types: tuple[str, ...]


type TownBounds = dict[str, float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import pubs/bars/nightclubs from Google Places into the venue map.")
    parser.add_argument("--town", default="Ballina", help="Town to search. Default: Ballina.")
    parser.add_argument("--county", default="Mayo", help="County to search. Default: Mayo.")
    parser.add_argument("--area-slug", default="", help="Area slug to use/create. Defaults to town-name-town.")
    parser.add_argument("--apply", action="store_true", help="Write changes to the database. Default is dry-run.")
    return parser.parse_args()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-co-[a-z]+$", "", slug)
    return slug


def normalise_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def load_town_bounds(town: str, county: str) -> TownBounds | None:
    if not IRELAND_LOCATIONS_PATH.exists():
        return None
    content = IRELAND_LOCATIONS_PATH.read_text(encoding="utf-8")
    match = re.search(r"export const IRELAND_LOCATIONS = (.+?) as const", content, flags=re.DOTALL)
    if not match:
        return None
    locations = json.loads(match.group(1))
    county_places = locations.get(county) or []
    town_key = normalise_text(town)
    for place in county_places:
        if normalise_text(place.get("name", "")) == town_key:
            return place.get("bounds")
    return None


def inside_bounds(latitude: float, longitude: float, bounds: TownBounds | None) -> bool:
    if bounds is None:
        return True
    return (
        latitude <= bounds["north"]
        and latitude >= bounds["south"]
        and longitude <= bounds["east"]
        and longitude >= bounds["west"]
    )


def is_town_result(address: str, town: str, county: str) -> bool:
    normalised = normalise_text(address)
    town_key = normalise_text(town)
    county_key = normalise_text(county)
    if county_key not in normalised:
        return False
    if re.search(rf"\b{re.escape(town_key)}\b", normalised):
        return True
    compact = normalised.replace(" ", "")
    return town_key.replace(" ", "") in compact


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
    non_nightlife_only = ("cinema", "movie", "leisure point", "restaurant", "hotel", "cafe", "coffee")
    if any(keyword in lowered for keyword in non_nightlife_only):
        return False
    nightlife_keywords = ("bar", "pub", "club", "nightclub", "cocktail", "loft", "tavern", "lounge")
    if any(keyword in lowered for keyword in nightlife_keywords):
        return True
    return True


def should_import_place_types(place: dict[str, Any]) -> bool:
    types = set(place.get("types") or [])
    primary_type = place.get("primaryType")
    if primary_type:
        types.add(primary_type)
    excluded_types = {
        "movie_theater",
        "restaurant",
        "cafe",
        "coffee_shop",
        "lodging",
        "hotel",
        "event_venue",
    }
    nightlife_types = {"bar", "pub", "night_club"}
    if types & excluded_types and not types & nightlife_types:
        return False
    return True


def build_queries(town: str, county: str) -> list[tuple[str, str]]:
    return [(template.format(town=town, county=county), default_type) for template, default_type in QUERY_TEMPLATES]


def collect_places(client: GooglePlacesClient, town: str, county: str, bounds: TownBounds | None = None) -> list[ImportedPlace]:
    collected: dict[str, ImportedPlace] = {}
    for query, default_type in build_queries(town, county):
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
            latitude = float(latitude)
            longitude = float(longitude)
            if not inside_bounds(latitude, longitude, bounds):
                continue
            if not is_town_result(address, town, county):
                continue
            if not should_import_place(name):
                continue
            if not should_import_place_types(place):
                continue
            imported = ImportedPlace(
                place_id=place_id,
                name=name,
                address=address,
                latitude=latitude,
                longitude=longitude,
                google_maps_uri=place.get("googleMapsUri"),
                website_uri=place.get("websiteUri"),
                inferred_type=infer_type(name, default_type),
                source_query=query,
                place_types=tuple(place.get("types") or []),
            )
            existing = collected.get(place_id)
            if existing is None:
                collected[place_id] = imported
            elif existing.inferred_type == "Bar" and imported.inferred_type in {"Pub", "Nightclub"}:
                collected[place_id] = imported
    return sorted(collected.values(), key=lambda item: item.name.lower())


def area_slug_for(town: str, override: str = "") -> str:
    return override or f"{slugify(town)}-town"


def fetch_or_create_area(
    db: Any,
    town: str,
    county: str,
    slug: str,
    places: list[ImportedPlace],
    apply: bool,
    bounds: TownBounds | None = None,
) -> Any:
    area = db.execute("SELECT * FROM areas WHERE slug = ?", (slug,)).fetchone()
    if area is not None:
        return area

    if not places:
        raise SystemExit(f"No Google Places results found, so area '{slug}' cannot be created.")

    latitudes = [place.latitude for place in places]
    longitudes = [place.longitude for place in places]
    if bounds:
        center_lat = (bounds["north"] + bounds["south"]) / 2
        center_lng = (bounds["east"] + bounds["west"]) / 2
        bounds_north = bounds["north"]
        bounds_south = bounds["south"]
        bounds_east = bounds["east"]
        bounds_west = bounds["west"]
    else:
        center_lat = sum(latitudes) / len(latitudes)
        center_lng = sum(longitudes) / len(longitudes)
        pad = 0.018
        bounds_north = max(latitudes) + pad
        bounds_south = min(latitudes) - pad
        bounds_east = max(longitudes) + pad
        bounds_west = min(longitudes) - pad

    if not apply:
        return {
            "id": None,
            "name": f"{town} Town",
            "slug": slug,
            "description": f"Google Places coverage for {town}, Co. {county}, Ireland.",
            "center_lat": center_lat,
            "center_lng": center_lng,
            "bounds_north": bounds_north,
            "bounds_south": bounds_south,
            "bounds_east": bounds_east,
            "bounds_west": bounds_west,
        }

    db.execute(
        """
        INSERT INTO areas
        (name, slug, description, center_lat, center_lng, bounds_north, bounds_south, bounds_east, bounds_west)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"{town} Town",
            slug,
            f"Google Places coverage for {town}, Co. {county}, Ireland.",
            center_lat,
            center_lng,
            bounds_north,
            bounds_south,
            bounds_east,
            bounds_west,
        ),
    )
    area = db.execute("SELECT * FROM areas WHERE slug = ?", (slug,)).fetchone()
    if area is None:
        raise SystemExit(f"Could not create area '{slug}'.")
    return area


def upsert_place(db: Any, area_id: int, town: str, place: ImportedPlace) -> str:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    slug = slugify(place.name)
    existing = db.execute(
        "SELECT id, slug, description, price_band, opens_at, closes_at, social_website FROM venues WHERE google_place_id = ? OR slug = ?",
        (place.place_id, slug),
    ).fetchone()

    description = (
        existing["description"]
        if existing and existing["description"]
        else f"Imported from Google Places for {town} map coverage. Opening hours, pricing, and events still need review."
    )
    price_band = existing["price_band"] if existing and existing["price_band"] else "TBC"
    opens_at = existing["opens_at"] if existing and existing["opens_at"] else "TBC"
    closes_at = existing["closes_at"] if existing and existing["closes_at"] else "TBC"
    social_website = existing["social_website"] if existing and existing["social_website"] else place.website_uri

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
    town = args.town.strip()
    county = args.county.strip()
    area_slug = area_slug_for(town, args.area_slug.strip())
    bounds = load_town_bounds(town, county)
    load_env_file()
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing GOOGLE_MAPS_API_KEY in .env")

    client = GooglePlacesClient(api_key)
    places = collect_places(client, town, county, bounds)
    if not places:
        print(f"No {town} venues were returned by Google Places.")
        return

    app = create_app()
    inserted = 0
    updated = 0
    with app.app_context():
        db = get_db()
        ensure_google_place_columns(db)
        area = fetch_or_create_area(db, town, county, area_slug, places, args.apply, bounds)
        print(f"Found {len(places)} {town} Google Places result(s). Mode: {'apply' if args.apply else 'dry-run'}")
        print(f"Area: {area['name'] if hasattr(area, 'keys') else area['name']} ({area_slug})")
        for place in places:
            print(f"- {place.name} | {place.inferred_type} | {place.address}")
            if args.apply:
                action = upsert_place(db, area["id"], town, place)
                if action == "inserted":
                    inserted += 1
                else:
                    updated += 1
        if args.apply:
            db.commit()

    if args.apply:
        print(f"\nApplied changes. Inserted {inserted}, updated {updated}.")
    else:
        print(f"\nDry-run only. Re-run with --apply to write these venues into the {town} map.")


if __name__ == "__main__":
    main()
