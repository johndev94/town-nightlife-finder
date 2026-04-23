from __future__ import annotations

from datetime import UTC, datetime

from app import create_app
from app.db import get_db


BALLINA_EVENT_SEED = [
    {
        "venue_slug": "bar-square-ballina",
        "title": "Late Night DJ Sets",
        "description": "Official venue listing for Friday late-night DJ sets at Bar Square.",
        "genre": "DJ",
        "start_at": "2026-04-24T23:30:00+01:00",
        "end_at": "2026-04-25T03:30:00+01:00",
        "price_label": "Check venue",
        "price_amount": None,
        "is_published": 1,
        "source_type": "website",
        "source_url": "https://www.barsquare-ballina.com/",
        "sync_status": "verified-reference",
        "confidence": 0.9,
    },
    {
        "venue_slug": "mcshanes-bar-ballina",
        "title": "Weekend Live Music Placeholder",
        "description": "Review placeholder based on the official venue text: live music and entertainment every weekend and on selected midweek nights. Exact act and time still need confirmation before publishing.",
        "genre": "Live Music",
        "start_at": "2026-04-25T21:00:00+01:00",
        "end_at": "2026-04-25T23:30:00+01:00",
        "price_label": "TBC",
        "price_amount": None,
        "is_published": 0,
        "source_type": "website",
        "source_url": "https://www.hotelballina.ie/mcshanes-bar/",
        "sync_status": "needs-review",
        "confidence": 0.45,
    },
    {
        "venue_slug": "the-merry-monk-ballina",
        "title": "Traditional Music Session Placeholder",
        "description": "Review placeholder based on the official venue text: regular traditional music sessions are held here. Exact date and time still need confirmation before publishing.",
        "genre": "Traditional",
        "start_at": "2026-04-24T21:00:00+01:00",
        "end_at": "2026-04-24T23:00:00+01:00",
        "price_label": "TBC",
        "price_amount": None,
        "is_published": 0,
        "source_type": "website",
        "source_url": "https://www.themerrymonk.ie/bar-in-ballina/",
        "sync_status": "needs-review",
        "confidence": 0.4,
    },
]


def main() -> None:
    app = create_app()
    with app.app_context():
        db = get_db()
        venue_rows = db.execute("SELECT id, slug FROM venues").fetchall()
        venue_ids = {row["slug"]: row["id"] for row in venue_rows}

        inserted = []
        for event in BALLINA_EVENT_SEED:
            venue_id = venue_ids.get(event["venue_slug"])
            if venue_id is None:
                print(f"Skipping missing venue: {event['venue_slug']}")
                continue

            existing = db.execute(
                "SELECT id FROM events WHERE venue_id = ? AND title = ? AND start_at = ?",
                (venue_id, event["title"], event["start_at"]),
            ).fetchone()

            values = (
                event["title"],
                event["description"],
                event["genre"],
                event["start_at"],
                event["end_at"],
                event["price_label"],
                event["price_amount"],
                event["is_published"],
                event["source_type"],
                event["source_url"],
                event["sync_status"],
                event["confidence"],
                datetime.now(UTC).isoformat(timespec="seconds"),
            )

            if existing:
                db.execute(
                    """
                    UPDATE events
                    SET title = ?, description = ?, genre = ?, start_at = ?, end_at = ?, price_label = ?,
                        price_amount = ?, is_published = ?, source_type = ?, source_url = ?, sync_status = ?,
                        confidence = ?, last_verified_at = ?
                    WHERE id = ?
                    """,
                    (*values, existing["id"]),
                )
                inserted.append((event["title"], "updated"))
            else:
                db.execute(
                    """
                    INSERT INTO events
                    (
                        venue_id, title, description, genre, start_at, end_at, price_label, price_amount,
                        currency, is_published, source_type, source_url, sync_status, confidence, last_verified_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'EUR', ?, ?, ?, ?, ?, ?)
                    """,
                    (venue_id, *values),
                )
                inserted.append((event["title"], "inserted"))

        db.commit()

    print("Ballina event seed complete:")
    for title, status in inserted:
        print(f"- {title}: {status}")


if __name__ == "__main__":
    main()
