from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests

from app import create_app
from app.db import get_db
from app.facebook_page_discovery import best_confident_candidate, discover_facebook_page_candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Find likely Facebook page URLs for Ballina venues.")
    parser.add_argument("--area", default="ballina-town", help="Area slug to search. Defaults to ballina-town.")
    parser.add_argument("--slug", help="Only search one venue slug.")
    parser.add_argument("--all", action="store_true", help="Include venues that already have a Facebook page URL.")
    parser.add_argument("--apply", action="store_true", help="Save confident matches to venues.social_facebook.")
    parser.add_argument("--min-score", type=float, default=0.72, help="Minimum score required to save a match.")
    parser.add_argument("--min-gap", type=float, default=0.08, help="Minimum lead over the second-best candidate.")
    parser.add_argument("--max-candidates", type=int, default=5, help="How many candidates to keep per venue.")
    parser.add_argument("--output", help="Optional JSON report path.")
    args = parser.parse_args()

    app = create_app()
    report: list[dict] = []
    applied = 0

    with app.app_context():
        venues = load_venues(args.area, args.slug, include_existing=args.all)
        if not venues:
            raise SystemExit("No matching venues were found for discovery.")

        db = get_db()
        for venue in venues:
            entry = {
                "venue": {"id": venue["id"], "name": venue["name"], "slug": venue["slug"]},
                "existing_facebook_url": venue["social_facebook"],
                "status": "pending",
                "selected": None,
                "candidates": [],
                "error": None,
            }
            try:
                candidates = discover_facebook_page_candidates(
                    venue_name=venue["name"],
                    town="Ballina",
                    county="Mayo",
                    website_url=venue["social_website"],
                    max_candidates=args.max_candidates,
                )
                entry["candidates"] = [candidate.to_dict() for candidate in candidates]
                selected = best_confident_candidate(candidates, min_score=args.min_score, min_gap=args.min_gap)
                entry["selected"] = selected.to_dict() if selected else None
                if selected is None:
                    entry["status"] = "ambiguous" if candidates and candidates[0].score >= 0.3 else "no-match"
                elif args.apply:
                    db.execute("UPDATE venues SET social_facebook = ? WHERE id = ?", (selected.url, venue["id"]))
                    applied += 1
                    entry["status"] = "applied"
                else:
                    entry["status"] = "ready"
            except requests.RequestException as exc:
                entry["status"] = "error"
                entry["error"] = str(exc)
            report.append(entry)

        if args.apply:
            db.commit()

    payload = {
        "checked": len(report),
        "applied": applied,
        "min_score": args.min_score,
        "min_gap": args.min_gap,
        "results": report,
    }
    output = json.dumps(payload, indent=2)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Wrote Facebook page discovery report to {args.output}")
    else:
        print(output)
    if not args.apply:
        print("Dry-run only. Re-run with --apply to save confident matches.")


def load_venues(area: str, slug: str | None, include_existing: bool):
    query = """
        SELECT v.id, v.name, v.slug, v.social_facebook, v.social_website
        FROM venues v
        JOIN areas a ON a.id = v.area_id
        WHERE a.slug = ?
    """
    params: list[object] = [area]
    if not include_existing:
        query += " AND (v.social_facebook IS NULL OR v.social_facebook = '')"
    if slug:
        query += " AND v.slug = ?"
        params.append(slug)
    query += " ORDER BY v.name"
    return get_db().execute(query, params).fetchall()


if __name__ == "__main__":
    main()
