from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import requests

from app import create_app
from app.apify_facebook import (
    build_event_description,
    collect_post_image_urls,
    extract_events_from_posts,
    extract_post_image_text,
    infer_start_at,
    looks_like_event,
    normalize_display_text,
    ocr_is_available,
    post_text,
    run_facebook_posts_scraper,
)
from app.db import get_db


def load_env_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull public Facebook posts with Apify and import event-like posts.")
    parser.add_argument("--area", default="ballina-town", help="Area slug to sync. Defaults to Ballina.")
    parser.add_argument("--slug", help="Only sync one venue slug.")
    parser.add_argument("--posts-per-page", type=int, default=20, help="Apify post limit per Facebook page.")
    parser.add_argument("--newer-than", default="3 months", help="Apify onlyPostsNewerThan value.")
    parser.add_argument("--apply", action="store_true", help="Write extracted events into the database.")
    parser.add_argument("--publish", action="store_true", help="Publish imported events immediately. Otherwise they are drafts.")
    parser.add_argument("--output", help="Optional JSON report path.")
    parser.add_argument("--debug-posts", action="store_true", help="Include fetched post previews and parser hints in the report.")
    parser.add_argument("--debug-post-limit", type=int, default=5, help="How many posts per venue to include in debug output.")
    args = parser.parse_args()

    load_env_file()
    token = os.environ.get("APIFY_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("APIFY_API_TOKEN is missing. Add it to .env before running this command.")

    app = create_app()
    report: list[dict] = []
    imported = 0

    with app.app_context():
        venues = load_facebook_venues(args.area, args.slug)
        if not venues:
            raise SystemExit("No venues with Facebook page URLs were found for that selection.")

        for venue in venues:
            venue_report = {
                "venue": {"id": venue["id"], "name": venue["name"], "slug": venue["slug"]},
                "facebook_url": venue["social_facebook"],
                "status": "pending",
                "events": [],
                "error": None,
            }
            try:
                posts = run_facebook_posts_scraper(
                    token=token,
                    page_url=venue["social_facebook"],
                    results_limit=args.posts_per_page,
                    newer_than=args.newer_than,
                )
                venue_report["posts_fetched"] = len(posts)
                events = extract_events_from_posts(posts, venue["name"])
                venue_report["status"] = "parsed"
                venue_report["events"] = [event.to_dict() for event in events]
                if args.debug_posts:
                    venue_report["post_previews"] = build_post_previews(posts, args.debug_post_limit)
                if args.apply:
                    for event in events:
                        if upsert_event(venue["id"], event, publish=args.publish):
                            imported += 1
            except (requests.RequestException, ValueError) as exc:
                venue_report["status"] = "error"
                venue_report["error"] = str(exc)
            report.append(venue_report)

        if args.apply:
            get_db().commit()

    payload = {"checked": len(report), "imported": imported, "applied": args.apply, "published": args.publish, "results": report}
    payload["ocr_available"] = ocr_is_available()
    output = json.dumps(payload, indent=2)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Wrote Apify Facebook sync report to {args.output}")
    else:
        print(output)
    if not args.apply:
        print("Dry-run only. Re-run with --apply to insert events, or --apply --publish to show them publicly.")


def load_facebook_venues(area: str, slug: str | None):
    query = """
        SELECT v.id, v.name, v.slug, v.social_facebook
        FROM venues v
        JOIN areas a ON a.id = v.area_id
        WHERE v.is_published = 1
          AND v.social_facebook IS NOT NULL
          AND v.social_facebook != ''
          AND a.slug = ?
    """
    params: list[object] = [area]
    if slug:
        query += " AND v.slug = ?"
        params.append(slug)
    query += " ORDER BY v.name"
    return get_db().execute(query, params).fetchall()


def upsert_event(venue_id: int, event, publish: bool) -> bool:
    db = get_db()
    existing = db.execute(
        """
        SELECT id FROM events
        WHERE venue_id = ?
          AND LOWER(title) = LOWER(?)
          AND start_at = ?
        """,
        (venue_id, event.title, event.start_at),
    ).fetchone()

    now = datetime.now(UTC).isoformat(timespec="seconds")
    values = (
        event.description,
        event.genre,
        event.end_at,
        event.price_label,
        event.price_amount,
        1 if publish else 0,
        event.source_url,
        event.confidence,
        now,
        venue_id,
        event.title,
        event.start_at,
    )
    if existing:
        db.execute(
            """
            UPDATE events
            SET description = ?, genre = ?, end_at = ?, price_label = ?, price_amount = ?,
                currency = 'EUR', is_published = ?, source_type = 'facebook-apify',
                source_url = ?, sync_status = 'needs-review', confidence = ?, last_verified_at = ?
            WHERE venue_id = ? AND LOWER(title) = LOWER(?) AND start_at = ?
            """,
            values,
        )
        return False

    db.execute(
        """
        INSERT INTO events
        (
            venue_id, title, description, genre, start_at, end_at, price_label,
            price_amount, currency, is_published, source_type, source_url,
            sync_status, confidence, last_verified_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'EUR', ?, 'facebook-apify', ?, 'needs-review', ?, ?)
        """,
        (
            venue_id,
            event.title,
            event.description,
            event.genre,
            event.start_at,
            event.end_at,
            event.price_label,
            event.price_amount,
            1 if publish else 0,
            event.source_url,
            event.confidence,
            now,
        ),
    )
    return True


def build_post_previews(posts: list[dict], limit: int) -> list[dict]:
    previews = []
    reference = datetime.now(UTC)
    for post in posts[:limit]:
        text = post_text(post)
        image_urls = collect_post_image_urls(post)
        ocr_text = extract_post_image_text(post) if image_urls else ""
        merged_text = f"{text} {ocr_text}".strip()
        previews.append(
            {
                "url": next((post.get(key) for key in ("url", "postUrl", "facebookUrl", "link") if post.get(key)), None),
                "timestamp": next((post.get(key) for key in ("time", "timestamp", "date", "createdAt", "creationTime") if post.get(key)), None),
                "image_count": len(image_urls),
                "image_urls": image_urls[:3],
                "ocr_preview": normalize_display_text(ocr_text)[:280] if ocr_text else "",
                "looks_like_event": looks_like_event(merged_text),
                "inferred_start_at": infer_start_at(merged_text, post, reference),
                "preview": normalize_display_text(build_event_description(post))[:280],
            }
        )
    return previews


if __name__ == "__main__":
    main()
