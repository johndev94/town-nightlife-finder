import argparse
import json
from pathlib import Path

from app import create_app
from app.db import get_db
from app.scraper import scrape_url


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape venue source URLs and emit a structured event extraction report."
    )
    parser.add_argument("--slug", help="Scrape only one venue slug.")
    parser.add_argument("--area", help="Scrape only one area slug.")
    parser.add_argument(
        "--output",
        help="Optional path to write the scrape report as JSON.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of venues to process.",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        rows = load_sources(args.slug, args.area, args.limit)
        results = []
        for row in rows:
            result = scrape_url(row["source_url"])
            results.append(
                {
                    "venue": {
                        "id": row["id"],
                        "name": row["name"],
                        "slug": row["slug"],
                    },
                    **result.to_dict(),
                }
            )

    payload = {"count": len(results), "results": results}
    text = json.dumps(payload, indent=2)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(text, encoding="utf-8")
        print(f"Wrote scrape report to {output_path}")
    else:
        print(text)


def load_sources(slug: str | None, area: str | None, limit: int):
    db = get_db()
    query = """
        SELECT v.id, v.name, v.slug, v.source_url
        FROM venues v
        JOIN areas a ON a.id = v.area_id
        WHERE is_published = 1
          AND source_url IS NOT NULL
          AND source_url != ''
    """
    params: list[object] = []
    if slug:
        query += " AND v.slug = ?"
        params.append(slug)
    if area:
        query += " AND a.slug = ?"
        params.append(area)
    query += " ORDER BY v.name LIMIT ?"
    params.append(limit)
    return db.execute(query, params).fetchall()


if __name__ == "__main__":
    main()
