from __future__ import annotations

from datetime import UTC, datetime

from app import create_app
from app.db import get_db


BALLINA_AREA = {
    "name": "Ballina Town",
    "slug": "ballina-town",
    "description": "Starter nightlife coverage for Ballina, Co. Mayo, Ireland.",
    "center_lat": 54.1159,
    "center_lng": -9.1536,
    "bounds_north": 54.1238,
    "bounds_south": 54.1082,
    "bounds_east": -9.1395,
    "bounds_west": -9.1708,
}


BALLINA_VENUES = [
    {
        "name": "Bar Square Ballina",
        "slug": "bar-square-ballina",
        "venue_type": "Bar",
        "address": "Garden St, Ballina, Co. Mayo",
        "description": "Food, drinks and live music venue in the heart of Ballina with a listed What's On schedule.",
        "price_band": "EUR-EUR",
        "latitude": 54.1148,
        "longitude": -9.1542,
        "opens_at": "12:00",
        "closes_at": "23:30",
        "social_facebook": None,
        "social_instagram": None,
        "social_website": "https://www.barsquare-ballina.com/",
        "source_type": "website",
        "source_url": "https://www.barsquare-ballina.com/",
        "sync_status": "needs-review",
        "confidence": 0.82,
        "platform": "Website",
        "notes": "Official venue site with opening hours and What's On listings.",
        "hours": [
            (0, "12:00", "23:30", 0),
            (1, "12:00", "23:30", 0),
            (2, "12:00", "23:30", 0),
            (3, "12:00", "23:30", 0),
            (4, "12:00", "03:30", 1),
            (5, "12:00", "03:30", 1),
            (6, "12:00", "23:30", 0),
        ],
    },
    {
        "name": "Paddy Mac's Ballina",
        "slug": "paddy-macs-ballina",
        "venue_type": "Pub",
        "address": "Garden St, Ballina, Co. Mayo",
        "description": "Traditional Irish pub with regular live music and published opening hours.",
        "price_band": "EUR-EUR",
        "latitude": 54.1147,
        "longitude": -9.1544,
        "opens_at": "12:00",
        "closes_at": "23:30",
        "social_facebook": None,
        "social_instagram": None,
        "social_website": "https://www.barsquare-ballina.com/paddy-macs",
        "source_type": "website",
        "source_url": "https://www.barsquare-ballina.com/paddy-macs",
        "sync_status": "needs-review",
        "confidence": 0.8,
        "platform": "Website",
        "notes": "Official venue page with opening hours and live music details.",
        "hours": [
            (0, "12:00", "23:30", 0),
            (1, "12:00", "23:30", 0),
            (2, "12:00", "23:30", 0),
            (3, "12:00", "23:30", 0),
            (4, "12:00", "03:30", 1),
            (5, "12:00", "03:30", 1),
            (6, "12:00", "23:30", 0),
        ],
    },
    {
        "name": "McShane's Bar Ballina",
        "slug": "mcshanes-bar-ballina",
        "venue_type": "Pub",
        "address": "N26 Dublin Road, Ballina, Co. Mayo",
        "description": "Hotel bar and bistro with weekend music and entertainment references on the official site.",
        "price_band": "EUR-EUR-EUR",
        "latitude": 54.1049,
        "longitude": -9.1343,
        "opens_at": "12:00",
        "closes_at": "23:30",
        "social_facebook": None,
        "social_instagram": None,
        "social_website": "https://www.hotelballina.ie/mcshanes-bar/",
        "source_type": "website",
        "source_url": "https://www.hotelballina.ie/mcshanes-bar/",
        "sync_status": "needs-review",
        "confidence": 0.68,
        "platform": "Website",
        "notes": "Official venue page references weekend music and entertainment; hours should be verified.",
        "hours": [
            (0, "12:00", "23:00", 0),
            (1, "12:00", "23:00", 0),
            (2, "12:00", "23:00", 0),
            (3, "12:00", "23:30", 0),
            (4, "12:00", "00:30", 1),
            (5, "12:00", "00:30", 1),
            (6, "12:00", "23:00", 0),
        ],
    },
    {
        "name": "The Merry Monk",
        "slug": "the-merry-monk-ballina",
        "venue_type": "Bar",
        "address": "Killala Rd, Ballina, Co. Mayo",
        "description": "Bar, event venue and accommodation with regular traditional music sessions listed on the official site.",
        "price_band": "EUR-EUR",
        "latitude": 54.1224,
        "longitude": -9.1457,
        "opens_at": "09:00",
        "closes_at": "23:30",
        "social_facebook": None,
        "social_instagram": None,
        "social_website": "https://www.themerrymonk.ie/bar-in-ballina/",
        "source_type": "website",
        "source_url": "https://www.themerrymonk.ie/bar-in-ballina/",
        "sync_status": "needs-review",
        "confidence": 0.84,
        "platform": "Website",
        "notes": "Official venue page lists opening hours and mentions regular traditional music sessions.",
        "hours": [
            (0, "09:00", "23:30", 0),
            (1, "09:00", "23:30", 0),
            (2, "09:00", "23:30", 0),
            (3, "09:00", "23:30", 0),
            (4, "09:00", "00:30", 1),
            (5, "09:00", "00:30", 1),
            (6, "12:00", "23:00", 0),
        ],
    },
]


def main() -> None:
    app = create_app()
    with app.app_context():
        db = get_db()
        area_id = upsert_area(db, BALLINA_AREA)
        inserted = []
        for venue in BALLINA_VENUES:
            venue_id = upsert_venue(db, area_id, venue)
            replace_hours(db, venue_id, venue["hours"])
            upsert_source(db, venue_id, venue)
            inserted.append((venue["slug"], venue["source_url"]))
        db.commit()

    print(f"Ballina starter data ready: {len(inserted)} venues")
    for slug, source_url in inserted:
        print(f"- {slug}: {source_url}")


def upsert_area(db, area: dict) -> int:
    existing = db.execute("SELECT id FROM areas WHERE slug = ?", (area["slug"],)).fetchone()
    values = (
        area["name"],
        area["description"],
        area["center_lat"],
        area["center_lng"],
        area["bounds_north"],
        area["bounds_south"],
        area["bounds_east"],
        area["bounds_west"],
        area["slug"],
    )
    if existing:
        db.execute(
            """
            UPDATE areas
            SET name = ?, description = ?, center_lat = ?, center_lng = ?,
                bounds_north = ?, bounds_south = ?, bounds_east = ?, bounds_west = ?
            WHERE slug = ?
            """,
            values,
        )
        return existing["id"]
    return db.execute(
        """
        INSERT INTO areas
        (name, slug, description, center_lat, center_lng, bounds_north, bounds_south, bounds_east, bounds_west)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            area["name"],
            area["slug"],
            area["description"],
            area["center_lat"],
            area["center_lng"],
            area["bounds_north"],
            area["bounds_south"],
            area["bounds_east"],
            area["bounds_west"],
        ),
    ).lastrowid


def upsert_venue(db, area_id: int, venue: dict) -> int:
    existing = db.execute("SELECT id FROM venues WHERE slug = ?", (venue["slug"],)).fetchone()
    now = datetime.now(UTC).isoformat(timespec="seconds")
    values = (
        area_id,
        venue["name"],
        venue["venue_type"],
        venue["address"],
        venue["description"],
        venue["price_band"],
        venue["latitude"],
        venue["longitude"],
        venue["opens_at"],
        venue["closes_at"],
        venue["social_facebook"],
        venue["social_instagram"],
        venue["social_website"],
        venue["source_type"],
        venue["source_url"],
        venue["sync_status"],
        venue["confidence"],
        now,
        venue["slug"],
    )
    if existing:
        db.execute(
            """
            UPDATE venues
            SET area_id = ?, name = ?, venue_type = ?, address = ?, description = ?, price_band = ?,
                latitude = ?, longitude = ?, opens_at = ?, closes_at = ?, social_facebook = ?,
                social_instagram = ?, social_website = ?, is_published = 1, source_type = ?,
                source_url = ?, sync_status = ?, confidence = ?, last_verified_at = ?
            WHERE slug = ?
            """,
            values,
        )
        return existing["id"]
    return db.execute(
        """
        INSERT INTO venues
        (
            area_id, name, slug, venue_type, address, description, price_band, latitude, longitude,
            opens_at, closes_at, social_facebook, social_instagram, social_website, is_published,
            source_type, source_url, sync_status, confidence, last_verified_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
        """,
        (
            area_id,
            venue["name"],
            venue["slug"],
            venue["venue_type"],
            venue["address"],
            venue["description"],
            venue["price_band"],
            venue["latitude"],
            venue["longitude"],
            venue["opens_at"],
            venue["closes_at"],
            venue["social_facebook"],
            venue["social_instagram"],
            venue["social_website"],
            venue["source_type"],
            venue["source_url"],
            venue["sync_status"],
            venue["confidence"],
            now,
        ),
    ).lastrowid


def replace_hours(db, venue_id: int, hours: list[tuple[int, str, str, int]]) -> None:
    db.execute("DELETE FROM opening_hours WHERE venue_id = ?", (venue_id,))
    for day_of_week, open_time, close_time, is_overnight in hours:
        db.execute(
            """
            INSERT INTO opening_hours (venue_id, day_of_week, open_time, close_time, is_overnight)
            VALUES (?, ?, ?, ?, ?)
            """,
            (venue_id, day_of_week, open_time, close_time, is_overnight),
        )


def upsert_source(db, venue_id: int, venue: dict) -> None:
    db.execute(
        "DELETE FROM sources WHERE entity_type = 'venue' AND entity_id = ? AND source_url = ?",
        (venue_id, venue["source_url"]),
    )
    db.execute(
        """
        INSERT INTO sources
        (entity_type, entity_id, platform, source_type, source_url, sync_status, confidence, last_verified_at, notes)
        VALUES ('venue', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            venue_id,
            venue["platform"],
            venue["source_type"],
            venue["source_url"],
            venue["sync_status"],
            venue["confidence"],
            datetime.now(UTC).isoformat(timespec="seconds"),
            venue["notes"],
        ),
    )


if __name__ == "__main__":
    main()
