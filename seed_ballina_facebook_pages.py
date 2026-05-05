from __future__ import annotations

from app import create_app
from app.db import get_db


BALLINA_FACEBOOK_PAGES = {
    "the-cot-and-cobble": "https://www.facebook.com/thecotandcobbleballina/",
    "hogan-s-cocktail-bar": "https://www.facebook.com/hogansballina/",
    "rouse-s-bar": "https://www.facebook.com/202400133126719",
    "the-merry-monk-ballina": "https://www.facebook.com/themerrymonk_ballina/",
}


def main() -> None:
    app = create_app()
    with app.app_context():
        db = get_db()
        updated = []
        missing = []
        for slug, facebook_url in BALLINA_FACEBOOK_PAGES.items():
            row = db.execute("SELECT id, name FROM venues WHERE slug = ?", (slug,)).fetchone()
            if row is None:
                missing.append(slug)
                continue
            db.execute(
                """
                UPDATE venues
                SET social_facebook = ?,
                    source_type = CASE WHEN source_type = 'google-places' THEN source_type ELSE source_type END
                WHERE slug = ?
                """,
                (facebook_url, slug),
            )
            updated.append((row["name"], facebook_url))
        db.commit()

    print(f"Seeded {len(updated)} Ballina Facebook page URL(s).")
    for name, facebook_url in updated:
        print(f"- {name}: {facebook_url}")
    if missing:
        print("Missing venue slug(s): " + ", ".join(missing))


if __name__ == "__main__":
    main()
