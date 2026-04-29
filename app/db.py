import sqlite3
from datetime import UTC, datetime

from flask import current_app, g


SCHEMA = """
CREATE TABLE IF NOT EXISTS areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    center_lat REAL NOT NULL,
    center_lng REAL NOT NULL,
    bounds_north REAL NOT NULL,
    bounds_south REAL NOT NULL,
    bounds_east REAL NOT NULL,
    bounds_west REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'owner')),
    venue_id INTEGER
);

CREATE TABLE IF NOT EXISTS venues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    venue_type TEXT NOT NULL,
    address TEXT NOT NULL,
    description TEXT NOT NULL,
    price_band TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    opens_at TEXT NOT NULL,
    closes_at TEXT NOT NULL,
    social_facebook TEXT,
    social_instagram TEXT,
    social_website TEXT,
    google_place_id TEXT,
    google_maps_uri TEXT,
    is_published INTEGER NOT NULL DEFAULT 1,
    source_type TEXT NOT NULL,
    source_url TEXT,
    sync_status TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    last_verified_at TEXT NOT NULL,
    claimed_by_user_id INTEGER
);

CREATE TABLE IF NOT EXISTS opening_hours (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue_id INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL,
    open_time TEXT NOT NULL,
    close_time TEXT NOT NULL,
    is_overnight INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    genre TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    price_label TEXT NOT NULL,
    price_amount REAL,
    currency TEXT NOT NULL DEFAULT 'GBP',
    is_published INTEGER NOT NULL DEFAULT 1,
    source_type TEXT NOT NULL,
    source_url TEXT,
    sync_status TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    last_verified_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('venue', 'event')),
    entity_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT,
    sync_status TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    last_verified_at TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS venue_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue_id INTEGER NOT NULL,
    claimant_name TEXT NOT NULL,
    claimant_email TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);
"""


AREA_SEED = [
    ("Old Town", "old-town", "Historic pubs and karaoke-heavy late bars around the market square.", 53.9582, -1.0805, 53.9635, 53.9545, -1.0740, -1.0865),
    ("Riverside", "riverside", "Warehouse clubs, beer halls, and larger dance venues near the quay.", 53.9540, -1.0680, 53.9585, 53.9495, -1.0610, -1.0745),
    ("Station Quarter", "station-quarter", "Convenient pre-drinks venues and live-music bars close to transport links.", 53.9605, -1.0895, 53.9648, 53.9564, -1.0835, -1.0955),
]


VENUE_SEED = [
    {
        "area_slug": "old-town",
        "name": "The Lantern Arms",
        "slug": "the-lantern-arms",
        "venue_type": "Pub",
        "address": "12 Market Row",
        "description": "A friendly old-town pub known for singalongs, sport, and late karaoke Thursdays.",
        "price_band": "££",
        "latitude": 53.9588,
        "longitude": -1.0814,
        "opens_at": "15:00",
        "closes_at": "00:30",
        "social_facebook": "https://facebook.com/lanternarms",
        "social_instagram": "https://instagram.com/lanternarms",
        "social_website": "https://lanternarms.example.com",
        "is_published": 1,
        "source_type": "manual",
        "source_url": "https://lanternarms.example.com/events",
        "sync_status": "verified",
        "confidence": 0.94,
        "last_verified_at": "2026-03-30T18:00:00",
        "hours": [(0, "15:00", "23:00", 0), (1, "15:00", "23:00", 0), (2, "15:00", "23:00", 0), (3, "15:00", "00:30", 0), (4, "12:00", "01:00", 0), (5, "12:00", "01:00", 0), (6, "12:00", "22:30", 0)],
        "events": [("Karaoke Night", "Open mic karaoke with drink deals before 8pm.", "Karaoke", "2026-04-02T20:00:00", "2026-04-02T23:30:00", "Free entry", 0, 1), ("Quiz & Vinyl", "Pub quiz followed by crowd-picked vinyl classics.", "Quiz", "2026-04-01T19:00:00", "2026-04-01T22:00:00", "£3 per team", 3, 1)],
    },
    {
        "area_slug": "old-town",
        "name": "Velvet Room",
        "slug": "velvet-room",
        "venue_type": "Nightclub",
        "address": "18 Stonegate",
        "description": "Late-night club with themed pop nights and DJ takeovers.",
        "price_band": "£££",
        "latitude": 53.9574,
        "longitude": -1.0790,
        "opens_at": "20:00",
        "closes_at": "03:00",
        "social_facebook": "https://facebook.com/velvetroom",
        "social_instagram": "https://instagram.com/velvetroom",
        "social_website": "https://velvetroom.example.com",
        "is_published": 1,
        "source_type": "owner",
        "source_url": "https://velvetroom.example.com",
        "sync_status": "owner-updated",
        "confidence": 0.90,
        "last_verified_at": "2026-03-31T09:30:00",
        "hours": [(3, "20:00", "02:00", 1), (4, "20:00", "03:00", 1), (5, "20:00", "03:00", 1), (6, "18:00", "01:00", 1)],
        "events": [("Pop Icons Friday", "Big room pop, throwback remixes, and confetti drop at midnight.", "Pop", "2026-04-03T21:00:00", "2026-04-04T02:30:00", "£9 advance / £12 door", 9, 1), ("Student Social", "Discounted cocktails and chart edits before midnight.", "Dance", "2026-04-01T22:00:00", "2026-04-02T02:00:00", "£5 before 11pm", 5, 0)],
    },
    {
        "area_slug": "riverside",
        "name": "Dockside Social",
        "slug": "dockside-social",
        "venue_type": "Bar",
        "address": "4 Quay Walk",
        "description": "Cocktail bar with terrace seating, soul DJs, and tasting flights.",
        "price_band": "£££",
        "latitude": 53.9535,
        "longitude": -1.0674,
        "opens_at": "16:00",
        "closes_at": "01:00",
        "social_facebook": "https://facebook.com/docksidesocial",
        "social_instagram": "https://instagram.com/docksidesocial",
        "social_website": "https://docksidesocial.example.com",
        "is_published": 1,
        "source_type": "external-reference",
        "source_url": "https://instagram.com/docksidesocial",
        "sync_status": "stale",
        "confidence": 0.74,
        "last_verified_at": "2026-03-20T18:45:00",
        "hours": [(1, "16:00", "00:00", 0), (2, "16:00", "00:00", 0), (3, "16:00", "00:00", 0), (4, "16:00", "01:00", 0), (5, "14:00", "01:00", 0), (6, "14:00", "23:00", 0)],
        "events": [("Soul on the Quay", "Resident DJs spin funk, disco, and soul with cocktail pairings.", "Soul", "2026-04-04T19:30:00", "2026-04-04T23:30:00", "Free before 9pm", 0, 1), ("Agave Tasting", "Guided mezcal and tequila tasting flight.", "Tasting", "2026-04-02T18:30:00", "2026-04-02T20:00:00", "£18 ticket", 18, 1)],
    },
    {
        "area_slug": "station-quarter",
        "name": "Platform 9 Bar",
        "slug": "platform-9-bar",
        "venue_type": "Bar",
        "address": "27 Rail Street",
        "description": "Casual station-side bar with live acoustic sessions and happy hour pints.",
        "price_band": "£",
        "latitude": 53.9609,
        "longitude": -1.0898,
        "opens_at": "12:00",
        "closes_at": "23:30",
        "social_facebook": "https://facebook.com/platform9bar",
        "social_instagram": "https://instagram.com/platform9bar",
        "social_website": "https://platform9bar.example.com",
        "is_published": 1,
        "source_type": "manual",
        "source_url": "https://platform9bar.example.com/whats-on",
        "sync_status": "verified",
        "confidence": 0.96,
        "last_verified_at": "2026-03-31T08:00:00",
        "hours": [(0, "12:00", "22:30", 0), (1, "12:00", "22:30", 0), (2, "12:00", "22:30", 0), (3, "12:00", "23:30", 0), (4, "12:00", "23:30", 0), (5, "12:00", "23:30", 0), (6, "12:00", "21:30", 0)],
        "events": [("Acoustic Thursdays", "Local songwriters play stripped-back sets from 7pm.", "Live Music", "2026-04-02T19:00:00", "2026-04-02T22:00:00", "Free", 0, 1)],
    },
]


USER_SEED = [("admin", "adminpass", "admin", None), ("velvet_owner", "ownerpass", "owner", "velvet-room")]

SOURCE_SEED = [
    ("venue", "the-lantern-arms", "Website", "manual", "https://lanternarms.example.com/events", "verified", 0.94, "2026-03-30T18:00:00", "Verified by admin"),
    ("venue", "velvet-room", "Instagram", "owner", "https://instagram.com/velvetroom", "owner-updated", 0.90, "2026-03-31T09:30:00", "Owner-confirmed schedule"),
    ("venue", "dockside-social", "Instagram", "external-reference", "https://instagram.com/docksidesocial", "stale", 0.74, "2026-03-20T18:45:00", "Needs manual verification"),
    ("event", "karaoke-night", "Website", "manual", "https://lanternarms.example.com/events", "verified", 0.93, "2026-03-30T18:00:00", "Copied from venue listing"),
    ("event", "pop-icons-friday", "Facebook", "owner", "https://facebook.com/velvetroom", "owner-updated", 0.89, "2026-03-31T09:30:00", "Owner confirmed on dashboard"),
]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    @app.before_request
    def ensure_database():
        init_db()


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    seed_if_empty(db)


def seed_if_empty(db):
    if db.execute("SELECT COUNT(*) AS count FROM areas").fetchone()["count"]:
        return

    db.executemany(
        """
        INSERT INTO areas
        (name, slug, description, center_lat, center_lng, bounds_north, bounds_south, bounds_east, bounds_west)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        AREA_SEED,
    )
    area_ids = {row["slug"]: row["id"] for row in db.execute("SELECT id, slug FROM areas")}

    for venue in VENUE_SEED:
        db.execute(
            """
            INSERT INTO venues
            (
                area_id, name, slug, venue_type, address, description, price_band, latitude, longitude,
                opens_at, closes_at, social_facebook, social_instagram, social_website, is_published,
                source_type, source_url, sync_status, confidence, last_verified_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                area_ids[venue["area_slug"]],
                venue["name"], venue["slug"], venue["venue_type"], venue["address"], venue["description"],
                venue["price_band"], venue["latitude"], venue["longitude"], venue["opens_at"], venue["closes_at"],
                venue["social_facebook"], venue["social_instagram"], venue["social_website"], venue["is_published"],
                venue["source_type"], venue["source_url"], venue["sync_status"], venue["confidence"], venue["last_verified_at"],
            ),
        )

    venue_ids = {row["slug"]: row["id"] for row in db.execute("SELECT id, slug FROM venues")}
    for username, password, role, venue_slug in USER_SEED:
        db.execute(
            "INSERT INTO users (username, password, role, venue_id) VALUES (?, ?, ?, ?)",
            (username, password, role, venue_ids.get(venue_slug)),
        )

    owner_id = db.execute("SELECT id FROM users WHERE username = 'velvet_owner'").fetchone()["id"]
    db.execute("UPDATE venues SET claimed_by_user_id = ? WHERE slug = 'velvet-room'", (owner_id,))

    event_ids = {}
    for venue in VENUE_SEED:
        venue_id = venue_ids[venue["slug"]]
        for day_of_week, open_time, close_time, is_overnight in venue["hours"]:
            db.execute(
                "INSERT INTO opening_hours (venue_id, day_of_week, open_time, close_time, is_overnight) VALUES (?, ?, ?, ?, ?)",
                (venue_id, day_of_week, open_time, close_time, is_overnight),
            )
        for event in venue["events"]:
            title, description, genre, start_at, end_at, price_label, price_amount, is_published = event
            event_id = db.execute(
                """
                INSERT INTO events
                (venue_id, title, description, genre, start_at, end_at, price_label, price_amount, currency, is_published, source_type, source_url, sync_status, confidence, last_verified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'GBP', ?, ?, ?, ?, ?, ?)
                """,
                (
                    venue_id, title, description, genre, start_at, end_at, price_label, price_amount, is_published,
                    venue["source_type"], venue["source_url"], venue["sync_status"], venue["confidence"], venue["last_verified_at"],
                ),
            ).lastrowid
            event_ids[slugify(title)] = event_id

    for entity_type, slug, platform, source_type, source_url, sync_status, confidence, last_verified_at, notes in SOURCE_SEED:
        entity_id = venue_ids[slug] if entity_type == "venue" else event_ids[slug]
        db.execute(
            "INSERT INTO sources (entity_type, entity_id, platform, source_type, source_url, sync_status, confidence, last_verified_at, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (entity_type, entity_id, platform, source_type, source_url, sync_status, confidence, last_verified_at, notes),
        )

    db.execute(
        "INSERT INTO venue_claims (venue_id, claimant_name, claimant_email, message, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (venue_ids["dockside-social"], "Nina Patel", "nina@dockside.example.com", "We'd like to claim the venue so our team can keep listings current.", "pending", datetime.now(UTC).isoformat(timespec="seconds")),
        )
    db.commit()


def slugify(value):
    return value.lower().replace("&", "and").replace("/", "-").replace(" ", "-")
