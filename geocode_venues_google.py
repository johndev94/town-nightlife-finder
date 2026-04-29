from __future__ import annotations

import argparse
import os
from typing import Any

from app import create_app
from app.db import get_db
from app.google_places import (
    GooglePlacesClient,
    apply_manual_location,
    apply_correction,
    ensure_google_place_columns,
    find_best_candidate,
    load_env_file,
    rate_limit_pause,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Correct venue locations with Google Places Text Search.")
    parser.add_argument("--apply", action="store_true", help="Write corrections to the database. Default is dry-run.")
    parser.add_argument("--area", help="Only correct venues in this area slug, for example ballina-town.")
    parser.add_argument("--slug", help="Only correct one venue slug.")
    parser.add_argument("--limit", type=int, help="Maximum number of venues to check.")
    parser.add_argument("--min-score", type=float, default=0.62, help="Minimum match score required before applying.")
    parser.add_argument("--no-address-update", action="store_true", help="Keep the existing address and only update coordinates/Google metadata.")
    parser.add_argument("--pause", type=float, default=0.15, help="Seconds to pause between Google requests.")
    parser.add_argument("--manual-lat", type=float, help="Manually set latitude for --slug.")
    parser.add_argument("--manual-lng", type=float, help="Manually set longitude for --slug.")
    parser.add_argument("--manual-address", help="Optional address to store with a manual coordinate correction.")
    return parser.parse_args()


def fetch_venues(db: Any, area: str | None, slug: str | None, limit: int | None) -> list[Any]:
    clauses = ["v.is_published = 1"]
    params: list[Any] = []
    if area:
        clauses.append("a.slug = ?")
        params.append(area)
    if slug:
        clauses.append("v.slug = ?")
        params.append(slug)

    sql = f"""
        SELECT v.*, a.name AS area_name, a.slug AS area_slug
        FROM venues v
        JOIN areas a ON a.id = v.area_id
        WHERE {" AND ".join(clauses)}
        ORDER BY a.name, v.name
    """
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return db.execute(sql, params).fetchall()


def print_correction(correction: Any, will_apply: bool) -> None:
    print(f"\n{correction.venue_name} ({correction.slug})")
    print(f"  Query: {correction.query}")
    print(f"  Current: {correction.current_address} [{correction.current_latitude}, {correction.current_longitude}]")
    if correction.error:
        print(f"  Error: {correction.error}")
        return
    if correction.candidate is None:
        print("  Google: no usable match found")
        return
    candidate = correction.candidate
    print(f"  Google: {candidate.name}")
    print(f"  Address: {candidate.address}")
    print(f"  Location: {candidate.latitude}, {candidate.longitude}")
    print(f"  Place ID: {candidate.place_id}")
    print(f"  Score: {candidate.score}")
    print(f"  Action: {'apply' if will_apply else 'dry-run'}")


def main() -> None:
    args = parse_args()
    load_env_file()

    app = create_app()
    applied = 0
    checked = 0

    with app.app_context():
        db = get_db()
        ensure_google_place_columns(db)

        if args.manual_lat is not None or args.manual_lng is not None:
            if not args.slug or args.manual_lat is None or args.manual_lng is None:
                raise SystemExit("Manual correction requires --slug, --manual-lat, and --manual-lng.")
            if not args.apply:
                print(
                    f"Dry-run manual correction for {args.slug}: "
                    f"{args.manual_lat}, {args.manual_lng}"
                )
                print("Re-run with --apply to update the database.")
                return
            updated = apply_manual_location(
                db,
                args.slug,
                args.manual_lat,
                args.manual_lng,
                address=args.manual_address,
                notes="Manual correction after reviewing Google/venue location.",
            )
            if not updated:
                raise SystemExit(f"No venue found for slug: {args.slug}")
            db.commit()
            print(f"Updated {args.slug} to {args.manual_lat}, {args.manual_lng}.")
            return

        api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
        if not api_key:
            raise SystemExit(
                "Missing GOOGLE_MAPS_API_KEY. Add it to .env or set it in PowerShell before running this command."
            )

        client = GooglePlacesClient(api_key)
        venues = fetch_venues(db, args.area, args.slug, args.limit)
        if not venues:
            print("No published venues matched those filters.")
            return

        print(f"Checking {len(venues)} venue(s) with Google Places. Mode: {'apply' if args.apply else 'dry-run'}")
        for venue in venues:
            correction = find_best_candidate(client, venue)
            checked += 1
            should_apply = args.apply and correction.can_apply and correction.candidate.score >= args.min_score
            print_correction(correction, should_apply)
            if should_apply:
                apply_correction(db, correction, update_address=not args.no_address_update)
                applied += 1
            rate_limit_pause(args.pause)

        if args.apply:
            db.commit()

    print(f"\nFinished. Checked {checked}, applied {applied}.")
    if not args.apply:
        print("Dry-run only. Re-run with --apply to update the database.")


if __name__ == "__main__":
    main()
