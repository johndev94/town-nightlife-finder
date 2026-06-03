import os
from pathlib import Path
from datetime import UTC, datetime
from functools import wraps

import requests
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for
from flask import current_app

from app.ai_event_cleaner import ai_cleanup_enabled, clean_event_with_ai
from app.apify_facebook import FacebookPostEvent, extract_events_from_posts, run_facebook_posts_scraper
from app.facebook_page_discovery import best_confident_candidate, discover_facebook_page_candidates
from app.google_places import GooglePlacesClient, ensure_google_place_columns, load_env_file

from import_ballina_google_places import area_slug_for, collect_places, fetch_or_create_area, load_town_bounds, slugify, upsert_place
from sync_facebook_events_apify import event_is_past, load_facebook_venues, upsert_event

from .db import get_db


bp = Blueprint("nightlife", __name__)


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT id, username, role, venue_id FROM users WHERE id = ?", (user_id,)).fetchone()


def dashboard_report():
    return session.pop("dashboard_report", None)


def dashboard_event_candidates():
    return session.get("event_candidates", [])


def dashboard_admin_summary():
    db = get_db()
    counts = db.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM areas) AS area_count,
            (SELECT COUNT(*) FROM venues) AS venue_count,
            (SELECT COUNT(*) FROM venues WHERE is_published = 1) AS published_venue_count,
            (SELECT COUNT(*) FROM venues WHERE is_published = 0) AS draft_venue_count,
            (SELECT COUNT(*) FROM venues WHERE social_facebook IS NULL OR social_facebook = '') AS missing_facebook_count,
            (SELECT COUNT(*) FROM venues WHERE social_facebook IS NOT NULL AND social_facebook != '') AS facebook_ready_count,
            (SELECT COUNT(*) FROM events) AS event_count,
            (SELECT COUNT(*) FROM events WHERE is_published = 1) AS published_event_count,
            (SELECT COUNT(*) FROM events WHERE is_published = 0) AS draft_event_count,
            (SELECT COUNT(*) FROM events WHERE confidence < 0.7 OR sync_status LIKE '%review%') AS needs_review_event_count,
            (SELECT COUNT(*) FROM venue_claims WHERE status = 'pending') AS pending_claim_count
        """
    ).fetchone()
    area_rows = db.execute(
        """
        SELECT
            a.name,
            a.slug,
            COUNT(DISTINCT v.id) AS venue_count,
            COUNT(DISTINCT CASE WHEN v.is_published = 1 THEN v.id END) AS published_venue_count,
            COUNT(DISTINCT CASE WHEN v.social_facebook IS NULL OR v.social_facebook = '' THEN v.id END) AS missing_facebook_count,
            COUNT(DISTINCT e.id) AS event_count,
            COUNT(DISTINCT CASE WHEN e.is_published = 1 THEN e.id END) AS published_event_count
        FROM areas a
        LEFT JOIN venues v ON v.area_id = a.id
        LEFT JOIN events e ON e.venue_id = v.id
        GROUP BY a.id
        ORDER BY a.name
        """
    ).fetchall()
    needs_facebook = db.execute(
        """
        SELECT v.id, v.name, v.slug, a.name AS area_name
        FROM venues v
        JOIN areas a ON a.id = v.area_id
        WHERE v.social_facebook IS NULL OR v.social_facebook = ''
        ORDER BY a.name, v.name
        LIMIT 8
        """
    ).fetchall()
    venue_drafts = db.execute(
        """
        SELECT v.id, v.name, v.slug, a.name AS area_name, v.sync_status
        FROM venues v
        JOIN areas a ON a.id = v.area_id
        WHERE v.is_published = 0 OR v.sync_status LIKE '%review%'
        ORDER BY v.is_published ASC, a.name, v.name
        LIMIT 8
        """
    ).fetchall()
    event_drafts = db.execute(
        """
        SELECT e.id, e.title, e.start_at, e.confidence, e.is_published, e.sync_status, v.name AS venue_name
        FROM events e
        JOIN venues v ON v.id = e.venue_id
        WHERE e.is_published = 0 OR e.confidence < 0.7 OR e.sync_status LIKE '%review%'
        ORDER BY e.is_published ASC, e.start_at ASC
        LIMIT 8
        """
    ).fetchall()
    return {"counts": counts, "areas": area_rows, "needs_facebook": needs_facebook, "venue_drafts": venue_drafts, "event_drafts": event_drafts}


def set_dashboard_report(title, rows, summary=None):
    status_counts = {}
    for row in rows:
        status = row.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    session["dashboard_report"] = {
        "title": title,
        "summary": summary or "",
        "rows": rows[:80],
        "status_counts": status_counts,
    }


def venue_report_row(status, primary, secondary, url=None, venue_id=None):
    return {
        "status": status,
        "primary": primary,
        "secondary": secondary,
        "url": url,
        "entity": "venue",
        "entity_id": venue_id,
    }


def event_report_row(status, primary, secondary, url=None, event_id=None):
    return {
        "status": status,
        "primary": primary,
        "secondary": secondary,
        "url": url,
        "entity": "event",
        "entity_id": event_id,
    }


def venue_id_for_google_place(db, place):
    row = db.execute("SELECT id FROM venues WHERE google_place_id = ? OR slug = ?", (place.place_id, slugify(place.name))).fetchone()
    return row["id"] if row else None


def event_id_for_sync(venue_id, event):
    row = get_db().execute(
        """
        SELECT id FROM events
        WHERE venue_id = ?
          AND start_at = ?
          AND (source_url = ? OR LOWER(title) = LOWER(?))
        ORDER BY last_verified_at DESC
        LIMIT 1
        """,
        (venue_id, event.start_at, event.source_url, event.title),
    ).fetchone()
    return row["id"] if row else None


def dashboard_queue():
    queue = request.args.get("queue", "all").strip().lower()
    allowed = {"all", "needs-facebook", "draft-pubs", "draft-events", "low-confidence", "published"}
    return queue if queue in allowed else "all"


def dashboard_queue_counts():
    db = get_db()
    return db.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM venues) AS all_count,
            (SELECT COUNT(*) FROM venues WHERE social_facebook IS NULL OR social_facebook = '') AS needs_facebook_count,
            (SELECT COUNT(*) FROM venues WHERE is_published = 0 OR sync_status LIKE '%review%') AS draft_pubs_count,
            (SELECT COUNT(*) FROM events WHERE is_published = 0 OR sync_status LIKE '%review%') AS draft_events_count,
            (SELECT COUNT(*) FROM events WHERE confidence < 0.7) AS low_confidence_count,
            (SELECT COUNT(*) FROM venues WHERE is_published = 1) + (SELECT COUNT(*) FROM events WHERE is_published = 1) AS published_count
        """
    ).fetchone()


def queue_label(queue):
    return {
        "all": "All records",
        "needs-facebook": "Needs Facebook",
        "draft-pubs": "Draft pubs",
        "draft-events": "Draft events",
        "low-confidence": "Low confidence events",
        "published": "Published",
    }.get(queue, "All records")


def dashboard_redirect():
    queue = request.form.get("queue", "").strip()
    if queue:
        return redirect(f"{url_for('nightlife.dashboard', queue=queue)}#review-queue")
    return redirect(f"{url_for('nightlife.dashboard')}#review-queue")


def dashboard_queue_redirect(queue):
    allowed = {"all", "needs-facebook", "draft-pubs", "draft-events", "low-confidence", "published"}
    safe_queue = queue if queue in allowed else "all"
    return redirect(f"{url_for('nightlife.dashboard', queue=safe_queue)}#review-queue")


def selected_int_ids(name):
    ids = []
    for value in request.form.getlist(name):
        try:
            parsed = int(value)
        except ValueError:
            abort(400)
        ids.append(parsed)
    return ids


def request_action():
    action = request.form.get("action", "preview").strip().lower()
    if action not in {"preview", "apply"}:
        abort(400)
    return action


def require_non_empty_form(*fields):
    values = {field: request.form.get(field, "").strip() for field in fields}
    if any(not value for value in values.values()):
        flash("Please complete all required admin tool fields.", "error")
        return None
    return values


def parse_positive_int(name, default, maximum):
    value = request.form.get(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        abort(400)
    return max(1, min(maximum, parsed))


def parse_float_form(name, default):
    value = request.form.get(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        abort(400)


def parse_optional_float(value):
    stripped = (value or "").strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def parse_bulk_lines(text):
    lines = []
    for line_number, line in enumerate((text or "").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = [part.strip() for part in stripped.split("|")]
        lines.append((line_number, parts))
    return lines


def unique_slug_for(db, table, base_slug, existing_id=None):
    slug = base_slug
    counter = 2
    while True:
        row = db.execute(f"SELECT id FROM {table} WHERE slug = ?", (slug,)).fetchone()
        if row is None or (existing_id and row["id"] == existing_id):
            return slug
        slug = f"{base_slug}-{counter}"
        counter += 1


def env_value(name):
    load_env_file()
    return os.environ.get(name, "").strip()


def town_from_area_name(area_name):
    return area_name.replace(" Town", "").strip() or area_name


def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                return redirect(url_for("nightlife.login", next=request.path))
            if role and user["role"] != role:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def normalize_filters(args):
    return {
        "area": args.get("area", "").strip(),
        "genre": args.get("genre", "").strip(),
        "venue_type": args.get("venue_type", "").strip(),
        "price_band": args.get("price_band", "").strip(),
        "date": args.get("date", "").strip(),
        "sort": args.get("sort", "time").strip(),
        "open_now": args.get("open_now", "").lower() in {"1", "true", "on", "yes"},
        "bounds_north": args.get("bounds_north", "").strip(),
        "bounds_south": args.get("bounds_south", "").strip(),
        "bounds_east": args.get("bounds_east", "").strip(),
        "bounds_west": args.get("bounds_west", "").strip(),
    }


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_venue_filters(filters):
    clauses = ["v.is_published = 1"]
    params = []
    if filters["area"]:
        clauses.append("a.slug = ?")
        params.append(filters["area"])
    else:
        north = to_float(filters["bounds_north"])
        south = to_float(filters["bounds_south"])
        east = to_float(filters["bounds_east"])
        west = to_float(filters["bounds_west"])
        if None not in {north, south, east, west}:
            clauses.extend(["v.latitude <= ?", "v.latitude >= ?", "v.longitude <= ?", "v.longitude >= ?"])
            params.extend([north, south, east, west])

    if filters["venue_type"]:
        clauses.append("LOWER(v.venue_type) = LOWER(?)")
        params.append(filters["venue_type"])
    if filters["price_band"]:
        clauses.append("v.price_band = ?")
        params.append(filters["price_band"])
    if filters["genre"]:
        clauses.append("EXISTS (SELECT 1 FROM events e2 WHERE e2.venue_id = v.id AND e2.is_published = 1 AND LOWER(e2.genre) = LOWER(?))")
        params.append(filters["genre"])
    if filters["open_now"]:
        now = datetime.now()
        weekday = now.weekday()
        current_time = now.strftime("%H:%M")
        clauses.append(
            "EXISTS (SELECT 1 FROM opening_hours oh WHERE oh.venue_id = v.id AND oh.day_of_week = ? AND ((oh.is_overnight = 0 AND ? BETWEEN oh.open_time AND oh.close_time) OR (oh.is_overnight = 1 AND (? >= oh.open_time OR ? <= oh.close_time))))"
        )
        params.extend([weekday, current_time, current_time, current_time])
    return " AND ".join(clauses), params


def fetch_areas():
    return get_db().execute("SELECT * FROM areas ORDER BY name").fetchall()


def fetch_filter_options():
    db = get_db()
    return {
        "venue_types": db.execute("SELECT DISTINCT venue_type FROM venues WHERE is_published = 1 ORDER BY venue_type").fetchall(),
        "genres": db.execute("SELECT DISTINCT genre FROM events WHERE is_published = 1 ORDER BY genre").fetchall(),
        "price_bands": db.execute("SELECT DISTINCT price_band FROM venues WHERE is_published = 1 ORDER BY price_band").fetchall(),
    }


def fetch_venues(filters):
    where_clause, params = build_venue_filters(filters)
    order_by = {
        "name": "v.name ASC",
        "price": "v.price_band ASC, v.name ASC",
        "area": "a.name ASC, v.name ASC",
        "time": "v.opens_at ASC, v.name ASC",
    }.get(filters["sort"], "v.opens_at ASC, v.name ASC")
    event_date_clause = "AND date(e.start_at) >= date(?)" if filters["date"] else ""
    event_date_params = [filters["date"]] if filters["date"] else []
    return get_db().execute(
        f"""
        SELECT v.*, a.name AS area_name, a.slug AS area_slug, COUNT(e.id) AS upcoming_event_count, MIN(e.start_at) AS next_event_start
        FROM venues v
        JOIN areas a ON a.id = v.area_id
        LEFT JOIN events e ON e.venue_id = v.id AND e.is_published = 1 {event_date_clause} AND (? = '' OR LOWER(e.genre) = LOWER(?))
        WHERE {where_clause}
        GROUP BY v.id
        ORDER BY {order_by}
        """,
        [*event_date_params, filters["genre"], filters["genre"], *params],
    ).fetchall()


def fetch_events(filters):
    where_clause, params = build_venue_filters(filters)
    event_clauses = ["e.is_published = 1"]
    event_params = []
    if filters["date"]:
        event_clauses.append("date(e.start_at) >= date(?)")
        event_params.append(filters["date"])
    if filters["genre"]:
        event_clauses.append("LOWER(e.genre) = LOWER(?)")
        event_params.append(filters["genre"])
    order_by = {
        "price": "COALESCE(e.price_amount, 0) ASC, e.start_at ASC",
        "name": "v.name ASC, e.start_at ASC",
        "area": "a.name ASC, e.start_at ASC",
        "time": "e.start_at ASC",
    }.get(filters["sort"], "e.start_at ASC")
    return get_db().execute(
        f"""
        SELECT e.*, v.name AS venue_name, v.slug AS venue_slug, v.venue_type, v.address, v.price_band, v.opens_at, v.closes_at, v.latitude, v.longitude, a.name AS area_name, a.slug AS area_slug
        FROM events e
        JOIN venues v ON v.id = e.venue_id
        JOIN areas a ON a.id = v.area_id
        WHERE {" AND ".join(event_clauses)} AND {where_clause}
        ORDER BY {order_by}
        """,
        [*event_params, *params],
    ).fetchall()


def format_venue(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "type": row["venue_type"],
        "address": row["address"],
        "description": row["description"],
        "price_band": row["price_band"],
        "area": {"name": row["area_name"], "slug": row["area_slug"]},
        "opens_at": row["opens_at"],
        "closes_at": row["closes_at"],
        "coordinates": {"lat": row["latitude"], "lng": row["longitude"]},
        "source": {"type": row["source_type"], "url": row["source_url"], "status": row["sync_status"], "confidence": row["confidence"], "last_verified_at": row["last_verified_at"]},
        "socials": {"facebook": row["social_facebook"], "instagram": row["social_instagram"], "website": row["social_website"]},
        "next_event_start": row["next_event_start"] if "next_event_start" in row.keys() else None,
        "upcoming_event_count": row["upcoming_event_count"] if "upcoming_event_count" in row.keys() else 0,
    }


def format_event(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "genre": row["genre"],
        "start_at": row["start_at"],
        "end_at": row["end_at"],
        "price_label": row["price_label"],
        "price_amount": row["price_amount"],
        "image_url": row["image_url"] if "image_url" in row.keys() else None,
        "venue": {"name": row["venue_name"], "slug": row["venue_slug"], "type": row["venue_type"], "address": row["address"], "price_band": row["price_band"], "opens_at": row["opens_at"], "closes_at": row["closes_at"], "coordinates": {"lat": row["latitude"], "lng": row["longitude"]}, "area": {"name": row["area_name"], "slug": row["area_slug"]}},
        "source": {"type": row["source_type"], "url": row["source_url"], "status": row["sync_status"], "confidence": row["confidence"], "last_verified_at": row["last_verified_at"]},
    }


def compute_osrm_route(from_coords, to_coords, mode="walking"):
    profile = {
        "walking": "foot",
        "driving": "driving",
        "cycling": "bike",
    }.get(mode, "foot")
    base_url = current_app.config["OSRM_BASE_URL"].rstrip("/")
    coordinates = f"{from_coords['lng']},{from_coords['lat']};{to_coords['lng']},{to_coords['lat']}"
    response = requests.get(
        f"{base_url}/route/v1/{profile}/{coordinates}",
        params={"overview": "full", "geometries": "geojson", "steps": "false"},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    routes = payload.get("routes") or []
    if not routes:
        raise ValueError("No route found")
    route = routes[0]
    coordinates_list = route.get("geometry", {}).get("coordinates") or []
    geometry = [{"lat": point[1], "lng": point[0]} for point in coordinates_list if len(point) >= 2]
    return {
        "distance_meters": route.get("distance"),
        "duration_seconds": route.get("duration"),
        "geometry": geometry,
        "mode": mode,
        "provider": "osrm",
    }


@bp.app_template_filter("datetimeformat")
def datetimeformat(value, fmt="%a %d %b, %H:%M"):
    if not value:
        return "TBC"
    return datetime.fromisoformat(value).strftime(fmt)


@bp.app_context_processor
def inject_user():
    return {"current_user": current_user()}


@bp.get("/")
def index():
    filters = normalize_filters(request.args)
    return render_template(
        "shell.html",
        app_config={"page": "home", "venueSlug": None},
        initial_data={
            "areas": [
                {
                    "id": area["id"],
                    "name": area["name"],
                    "slug": area["slug"],
                    "description": area["description"],
                    "center": {"lat": area["center_lat"], "lng": area["center_lng"]},
                    "bounds": {
                        "north": area["bounds_north"],
                        "south": area["bounds_south"],
                        "east": area["bounds_east"],
                        "west": area["bounds_west"],
                    },
                }
                for area in fetch_areas()
            ],
            "venues": [format_venue(row) for row in fetch_venues(filters)],
            "events": [format_event(row) for row in fetch_events(filters)],
        },
    )


@bp.get("/venues/<slug>")
def venue_detail(slug):
    db = get_db()
    venue = db.execute("SELECT v.*, a.name AS area_name, a.slug AS area_slug FROM venues v JOIN areas a ON a.id = v.area_id WHERE v.slug = ? AND v.is_published = 1", (slug,)).fetchone()
    if venue is None:
        abort(404)
    return render_template("shell.html", app_config={"page": "venue", "venueSlug": slug}, initial_data={})


@bp.get("/events/<int:event_id>")
def event_detail(event_id):
    event = get_db().execute(
        """
        SELECT e.id
        FROM events e
        JOIN venues v ON v.id = e.venue_id
        WHERE e.id = ? AND e.is_published = 1 AND v.is_published = 1
        """,
        (event_id,),
    ).fetchone()
    if event is None:
        abort(404)
    return render_template("shell.html", app_config={"page": "event", "venueSlug": None, "eventId": event_id}, initial_data={})


@bp.get("/api/areas")
def api_areas():
    return jsonify([
        {
            "id": area["id"],
            "name": area["name"],
            "slug": area["slug"],
            "description": area["description"],
            "center": {"lat": area["center_lat"], "lng": area["center_lng"]},
            "bounds": {"north": area["bounds_north"], "south": area["bounds_south"], "east": area["bounds_east"], "west": area["bounds_west"]},
        }
        for area in fetch_areas()
    ])


@bp.get("/api/venues")
def api_venues():
    return jsonify([format_venue(row) for row in fetch_venues(normalize_filters(request.args))])


@bp.get("/api/events")
def api_events():
    return jsonify([format_event(row) for row in fetch_events(normalize_filters(request.args))])


@bp.post("/api/route")
def api_route():
    payload = request.get_json(silent=True) or {}
    from_coords = payload.get("from")
    to_coords = payload.get("to")
    mode = (payload.get("mode") or "walking").strip().lower()

    if not isinstance(from_coords, dict) or not isinstance(to_coords, dict):
        return jsonify({"error": "Both 'from' and 'to' coordinates are required."}), 400

    try:
        from_lat = float(from_coords["lat"])
        from_lng = float(from_coords["lng"])
        to_lat = float(to_coords["lat"])
        to_lng = float(to_coords["lng"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Invalid route coordinates."}), 400

    try:
        route = compute_osrm_route(
            {"lat": from_lat, "lng": from_lng},
            {"lat": to_lat, "lng": to_lng},
            mode=mode,
        )
    except requests.RequestException:
        return jsonify({"error": "Routing service is unavailable right now."}), 502
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

    return jsonify(route)


@bp.get("/api/events/<int:event_id>")
def api_event_detail(event_id):
    row = get_db().execute(
        """
        SELECT e.*, v.name AS venue_name, v.slug AS venue_slug, v.venue_type, v.address, v.price_band,
               v.opens_at, v.closes_at, v.latitude, v.longitude, a.name AS area_name, a.slug AS area_slug
        FROM events e
        JOIN venues v ON v.id = e.venue_id
        JOIN areas a ON a.id = v.area_id
        WHERE e.id = ? AND e.is_published = 1 AND v.is_published = 1
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        abort(404)
    return jsonify(format_event(row))


@bp.get("/api/venues/<slug>")
def api_venue_detail(slug):
    db = get_db()
    venue = db.execute("SELECT v.*, a.name AS area_name, a.slug AS area_slug FROM venues v JOIN areas a ON a.id = v.area_id WHERE v.slug = ? AND v.is_published = 1", (slug,)).fetchone()
    if venue is None:
        abort(404)
    hours = db.execute("SELECT day_of_week, open_time, close_time, is_overnight FROM opening_hours WHERE venue_id = ? ORDER BY day_of_week", (venue["id"],)).fetchall()
    events = db.execute("SELECT * FROM events WHERE venue_id = ? AND is_published = 1 ORDER BY start_at ASC", (venue["id"],)).fetchall()
    payload = format_venue(venue)
    payload["opening_hours"] = [dict(hour) for hour in hours]
    payload["events"] = []
    for row in events:
        event_row = dict(row)
        event_row.update(
            {
                "venue_name": venue["name"],
                "venue_slug": venue["slug"],
                "venue_type": venue["venue_type"],
                "address": venue["address"],
                "price_band": venue["price_band"],
                "opens_at": venue["opens_at"],
                "closes_at": venue["closes_at"],
                "latitude": venue["latitude"],
                "longitude": venue["longitude"],
                "area_name": venue["area_name"],
                "area_slug": venue["area_slug"],
            }
        )
        payload["events"].append(format_event(event_row))
    return jsonify(payload)


@bp.post("/claims")
def create_claim():
    is_json = request.is_json
    payload = request.get_json(silent=True) if is_json else request.form
    venue_id = int(payload.get("venue_id")) if payload and payload.get("venue_id") else None
    claimant_name = (payload.get("claimant_name") or "").strip() if payload else ""
    claimant_email = (payload.get("claimant_email") or "").strip() if payload else ""
    message = (payload.get("message") or "").strip() if payload else ""
    next_path = (payload.get("next") if payload else None) or url_for("nightlife.index")
    if not all([venue_id, claimant_name, claimant_email, message]):
        if is_json:
            return jsonify({"ok": False, "error": "Please complete all claim request fields."}), 400
        flash("Please complete all claim request fields.", "error")
        return redirect(next_path)
    db = get_db()
    db.execute("INSERT INTO venue_claims (venue_id, claimant_name, claimant_email, message, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)", (venue_id, claimant_name, claimant_email, message, datetime.now(UTC).isoformat(timespec="seconds")))
    db.commit()
    if is_json:
        return jsonify({"ok": True, "message": "Claim request submitted. An admin can review it from the dashboard."}), 201
    flash("Claim request submitted. An admin can review it from the dashboard.", "success")
    return redirect(next_path)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = get_db().execute("SELECT id, username, role, venue_id FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
        if user is None:
            flash("Invalid username or password.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(request.args.get("next") or url_for("nightlife.dashboard"))
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("nightlife.index"))


def can_manage_venue(user, venue_id):
    if user["role"] == "admin":
        return True
    venue = get_db().execute("SELECT claimed_by_user_id FROM venues WHERE id = ?", (venue_id,)).fetchone()
    return venue is not None and venue["claimed_by_user_id"] == user["id"]


@bp.get("/dashboard")
@login_required()
def dashboard():
    user = current_user()
    db = get_db()
    admin_summary = None
    queue = dashboard_queue()
    queue_counts = None
    all_venues = []
    if user["role"] == "admin":
        venue_filter = ""
        event_filter = ""
        if queue == "needs-facebook":
            venue_filter = "WHERE v.social_facebook IS NULL OR v.social_facebook = ''"
            event_filter = "AND 1 = 0"
        elif queue == "draft-pubs":
            venue_filter = "WHERE v.is_published = 0 OR v.sync_status LIKE '%review%'"
            event_filter = "AND 1 = 0"
        elif queue == "draft-events":
            venue_filter = "WHERE 1 = 0"
            event_filter = "AND (e.is_published = 0 OR e.sync_status LIKE '%review%')"
        elif queue == "low-confidence":
            venue_filter = "WHERE 1 = 0"
            event_filter = "AND e.confidence < 0.7"
        elif queue == "published":
            venue_filter = "WHERE v.is_published = 1"
            event_filter = "AND e.is_published = 1"

        venues = db.execute(
            f"""
            SELECT
                v.*,
                a.name AS area_name,
                COUNT(e.id) AS event_count,
                COUNT(CASE WHEN e.is_published = 1 THEN 1 END) AS published_event_count,
                MAX(e.start_at) AS latest_event_start
            FROM venues v
            JOIN areas a ON a.id = v.area_id
            LEFT JOIN events e ON e.venue_id = v.id
            {venue_filter}
            GROUP BY v.id
            ORDER BY a.name, v.name
            """
        ).fetchall()
        all_venues = db.execute(
            """
            SELECT v.id, v.name, v.slug, v.social_facebook, v.social_website, a.name AS area_name
            FROM venues v
            JOIN areas a ON a.id = v.area_id
            ORDER BY a.name, v.name
            """
        ).fetchall()
        areas = db.execute("SELECT * FROM areas ORDER BY name").fetchall()
        claims = db.execute(
            """
            SELECT vc.*, v.name AS venue_name
            FROM venue_claims vc
            JOIN venues v ON v.id = vc.venue_id
            WHERE vc.status = 'pending'
            ORDER BY vc.created_at DESC
            """
        ).fetchall()
        admin_summary = dashboard_admin_summary()
        queue_counts = dashboard_queue_counts()
    else:
        venues = db.execute(
            """
            SELECT
                v.*,
                a.name AS area_name,
                COUNT(e.id) AS event_count,
                COUNT(CASE WHEN e.is_published = 1 THEN 1 END) AS published_event_count,
                MAX(e.start_at) AS latest_event_start
            FROM venues v
            JOIN areas a ON a.id = v.area_id
            LEFT JOIN events e ON e.venue_id = v.id
            WHERE v.claimed_by_user_id = ?
            GROUP BY v.id
            ORDER BY v.name
            """,
            (user["id"],),
        ).fetchall()
        areas = []
        claims = []
        event_filter = ""
    events = []
    if user["role"] == "admin":
        events = db.execute(
            f"""
            SELECT e.*, v.name AS venue_name
            FROM events e
            JOIN venues v ON v.id = e.venue_id
            WHERE 1 = 1 {event_filter}
            ORDER BY e.is_published ASC, e.start_at ASC
            """
        ).fetchall()
    elif venues:
        ids = [venue["id"] for venue in venues]
        query = ",".join("?" for _ in ids)
        events = db.execute(
            f"""
            SELECT e.*, v.name AS venue_name
            FROM events e
            JOIN venues v ON v.id = e.venue_id
            WHERE e.venue_id IN ({query})
            ORDER BY e.is_published ASC, e.start_at ASC
            """,
            ids,
        ).fetchall()
    return render_template(
        "dashboard.html",
        user=user,
        venues=venues,
        all_venues=all_venues or venues,
        events=events,
        claims=claims,
        areas=areas,
        admin_report=dashboard_report(),
        event_candidates=dashboard_event_candidates(),
        admin_summary=admin_summary,
        queue=queue,
        queue_label=queue_label(queue),
        queue_counts=queue_counts,
    )


@bp.post("/dashboard/venues/<int:venue_id>")
@login_required()
def update_venue(venue_id):
    user = current_user()
    if not can_manage_venue(user, venue_id):
        abort(403)
    existing = get_db().execute("SELECT is_published FROM venues WHERE id = ?", (venue_id,)).fetchone()
    if existing is None:
        abort(404)
    is_published = 1 if request.form.get("is_published") == "on" else 0
    if request.form.get("publish_control") != "1":
        is_published = existing["is_published"]
    get_db().execute(
        """
        UPDATE venues
        SET opens_at = ?, closes_at = ?, price_band = ?, social_facebook = ?, social_website = ?,
            is_published = ?, source_type = ?, source_url = ?, sync_status = ?, confidence = ?,
            last_verified_at = ?
        WHERE id = ?
        """,
        (
            request.form.get("opens_at", "").strip(),
            request.form.get("closes_at", "").strip(),
            request.form.get("price_band", "").strip(),
            request.form.get("social_facebook", "").strip(),
            request.form.get("social_website", "").strip(),
            is_published,
            request.form.get("source_type", "").strip() or "owner",
            request.form.get("source_url", "").strip(),
            request.form.get("sync_status", "").strip() or "owner-updated",
            request.form.get("confidence", type=float, default=0.75),
            datetime.now(UTC).isoformat(timespec="seconds"),
            venue_id,
        ),
    )
    get_db().commit()
    flash("Venue details updated.", "success")
    return dashboard_redirect()


@bp.post("/dashboard/events/<int:event_id>")
@login_required()
def update_event(event_id):
    db = get_db()
    event = db.execute("SELECT venue_id FROM events WHERE id = ?", (event_id,)).fetchone()
    if event is None or not can_manage_venue(current_user(), event["venue_id"]):
        abort(403)
    db.execute(
        "UPDATE events SET title = ?, genre = ?, start_at = ?, end_at = ?, price_label = ?, price_amount = ?, is_published = ?, sync_status = ?, source_type = ?, source_url = ?, last_verified_at = ? WHERE id = ?",
        (
            request.form.get("title", "").strip(),
            request.form.get("genre", "").strip(),
            request.form.get("start_at", "").strip(),
            request.form.get("end_at", "").strip(),
            request.form.get("price_label", "").strip(),
            request.form.get("price_amount", type=float),
            1 if request.form.get("is_published") == "on" else 0,
            request.form.get("sync_status", "").strip() or "owner-updated",
            request.form.get("source_type", "").strip() or "owner",
            request.form.get("source_url", "").strip(),
            datetime.now(UTC).isoformat(timespec="seconds"),
            event_id,
        ),
    )
    db.commit()
    flash("Event updated.", "success")
    return dashboard_redirect()


@bp.post("/dashboard/admin-tools/google-places")
@login_required(role="admin")
def admin_google_places_import():
    values = require_non_empty_form("town", "county")
    if values is None:
        return redirect(url_for("nightlife.dashboard"))
    action = request_action()
    area_slug = request.form.get("area_slug", "").strip() or area_slug_for(values["town"])
    api_key = env_value("GOOGLE_MAPS_API_KEY")
    if not api_key:
        flash("GOOGLE_MAPS_API_KEY is missing. Add it to your environment before importing venues.", "error")
        return redirect(url_for("nightlife.dashboard"))

    try:
        client = GooglePlacesClient(api_key)
        bounds = load_town_bounds(values["town"], values["county"])
        places = collect_places(client, values["town"], values["county"], bounds)
    except requests.RequestException as exc:
        flash(f"Google Places request failed: {exc}", "error")
        return redirect(url_for("nightlife.dashboard"))

    rows = [
        venue_report_row(
            "ready" if action == "preview" else "saved",
            place.name,
            f"{place.inferred_type} | {place.address}",
            place.google_maps_uri,
        )
        for place in places
    ]

    inserted = updated = 0
    if action == "apply" and places:
        db = get_db()
        ensure_google_place_columns(db)
        area = fetch_or_create_area(db, values["town"], values["county"], area_slug, places, True, bounds)
        for place in places:
            result = upsert_place(db, area["id"], values["town"], place)
            venue_id = venue_id_for_google_place(db, place)
            for row in rows:
                if row["primary"] == place.name:
                    row["entity_id"] = venue_id
            if result == "inserted":
                inserted += 1
            else:
                updated += 1
        db.commit()
        flash(f"Saved Google Places venues for {values['town']}. Inserted {inserted}, updated {updated}.", "success")
    elif not places:
        flash(f"No Google Places pub/bar results found for {values['town']}, Co. {values['county']}.", "error")
    else:
        flash(f"Previewed {len(places)} Google Places venue result(s). Nothing was saved yet.", "success")

    set_dashboard_report(
        f"Google Places {'save' if action == 'apply' else 'preview'}: {values['town']}",
        rows,
        f"{len(places)} result(s). Area slug: {area_slug}.",
    )
    return redirect(url_for("nightlife.dashboard"))


@bp.post("/dashboard/admin-tools/facebook-pages")
@login_required(role="admin")
def admin_facebook_page_discovery():
    values = require_non_empty_form("area")
    if values is None:
        return redirect(url_for("nightlife.dashboard"))
    action = request_action()
    min_score = parse_float_form("min_score", 0.68)
    min_gap = parse_float_form("min_gap", 0.04)
    include_existing = request.form.get("include_existing") == "on"
    db = get_db()
    area = db.execute("SELECT * FROM areas WHERE slug = ?", (values["area"],)).fetchone()
    if area is None:
        flash("Selected area was not found.", "error")
        return redirect(url_for("nightlife.dashboard"))

    venues = db.execute(
        """
        SELECT v.id, v.name, v.slug, v.social_facebook, v.social_website, a.name AS area_name
        FROM venues v
        JOIN areas a ON a.id = v.area_id
        WHERE a.slug = ?
          AND (? = 1 OR v.social_facebook IS NULL OR v.social_facebook = '')
        ORDER BY v.name
        """,
        (values["area"], 1 if include_existing else 0),
    ).fetchall()
    if not venues:
        flash("No venues need Facebook discovery in that area.", "error")
        return redirect(url_for("nightlife.dashboard"))

    town = request.form.get("town", "").strip() or town_from_area_name(area["name"])
    county = request.form.get("county", "").strip() or "Mayo"
    rows = []
    applied = 0
    for venue in venues:
        try:
            candidates = discover_facebook_page_candidates(
                venue_name=venue["name"],
                town=town,
                county=county,
                website_url=venue["social_website"],
                max_candidates=5,
            )
        except requests.RequestException as exc:
            rows.append(venue_report_row("error", venue["name"], str(exc), None, venue["id"]))
            continue

        selected = best_confident_candidate(candidates, min_score=min_score, min_gap=min_gap)
        if selected and action == "apply":
            db.execute("UPDATE venues SET social_facebook = ?, last_verified_at = ? WHERE id = ?", (selected.url, datetime.now(UTC).isoformat(timespec="seconds"), venue["id"]))
            applied += 1
        top = selected or (candidates[0] if candidates else None)
        rows.append(
            venue_report_row(
                "saved" if selected and action == "apply" else "ready" if selected else "needs-review" if candidates else "no-match",
                venue["name"],
                f"Score {top.score:.2f}: {top.title}" if top else "No likely Facebook page found",
                top.url if top else None,
                venue["id"],
            )
        )

    if action == "apply":
        db.commit()
        flash(f"Saved {applied} confident Facebook page link(s).", "success")
    else:
        flash("Facebook page discovery preview complete. Nothing was saved yet.", "success")
    set_dashboard_report(f"Facebook discovery: {area['name']}", rows, f"Checked {len(venues)} venue(s).")
    return redirect(url_for("nightlife.dashboard"))


@bp.post("/dashboard/admin-tools/venue-profile")
@login_required(role="admin")
def admin_update_venue_profile_link():
    values = require_non_empty_form("venue_id", "social_facebook")
    if values is None:
        return redirect(url_for("nightlife.dashboard"))
    try:
        venue_id = int(values["venue_id"])
    except ValueError:
        abort(400)
    if "facebook.com" not in values["social_facebook"].lower():
        flash("Please enter a Facebook page URL.", "error")
        return redirect(url_for("nightlife.dashboard"))
    db = get_db()
    venue = db.execute("SELECT name FROM venues WHERE id = ?", (venue_id,)).fetchone()
    if venue is None:
        abort(404)
    db.execute("UPDATE venues SET social_facebook = ?, last_verified_at = ? WHERE id = ?", (values["social_facebook"], datetime.now(UTC).isoformat(timespec="seconds"), venue_id))
    db.commit()
    flash(f"Saved Facebook page for {venue['name']}.", "success")
    set_dashboard_report("Manual Facebook page update", [venue_report_row("saved", venue["name"], "Official profile link saved", values["social_facebook"], venue_id)])
    return redirect(url_for("nightlife.dashboard"))


@bp.post("/dashboard/admin-tools/bulk-venues")
@login_required(role="admin")
def admin_bulk_venues():
    values = require_non_empty_form("area", "venue_rows")
    if values is None:
        return redirect(url_for("nightlife.dashboard"))
    action = request_action()
    publish = request.form.get("publish") == "on"
    db = get_db()
    area = db.execute("SELECT * FROM areas WHERE slug = ?", (values["area"],)).fetchone()
    if area is None:
        flash("Selected area was not found.", "error")
        return redirect(url_for("nightlife.dashboard"))

    rows = []
    saved = 0
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for line_number, parts in parse_bulk_lines(values["venue_rows"]):
        if len(parts) < 4:
            rows.append(venue_report_row("error", f"Line {line_number}", "Use: name | address | latitude | longitude | type | opens | closes | facebook"))
            continue
        name, address, latitude_text, longitude_text = parts[:4]
        venue_type = parts[4] if len(parts) > 4 and parts[4] else "Pub"
        opens_at = parts[5] if len(parts) > 5 and parts[5] else "TBC"
        closes_at = parts[6] if len(parts) > 6 and parts[6] else "TBC"
        facebook_url = parts[7] if len(parts) > 7 else ""
        latitude = parse_optional_float(latitude_text)
        longitude = parse_optional_float(longitude_text)
        if not name or not address or latitude is None or longitude is None:
            rows.append(venue_report_row("error", f"Line {line_number}", "Name, address, latitude, and longitude are required."))
            continue
        base_slug = slugify(name)
        existing = db.execute("SELECT id FROM venues WHERE slug = ?", (base_slug,)).fetchone()
        venue_id = existing["id"] if existing else None
        if action == "apply":
            if existing:
                db.execute(
                    """
                    UPDATE venues
                    SET area_id = ?, name = ?, venue_type = ?, address = ?, latitude = ?, longitude = ?,
                        opens_at = ?, closes_at = ?, social_facebook = COALESCE(NULLIF(?, ''), social_facebook),
                        is_published = ?, source_type = ?, sync_status = ?, confidence = ?, last_verified_at = ?
                    WHERE id = ?
                    """,
                    (
                        area["id"],
                        name,
                        venue_type,
                        address,
                        latitude,
                        longitude,
                        opens_at,
                        closes_at,
                        facebook_url,
                        1 if publish else 0,
                        "admin-bulk",
                        "admin-reviewed" if publish else "needs-review",
                        0.72,
                        now,
                        venue_id,
                    ),
                )
            else:
                venue_slug = unique_slug_for(db, "venues", base_slug)
                venue_id = db.execute(
                    """
                    INSERT INTO venues
                    (
                        area_id, name, slug, venue_type, address, description, price_band, latitude, longitude,
                        opens_at, closes_at, social_facebook, social_instagram, social_website,
                        is_published, source_type, source_url, sync_status, confidence, last_verified_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'TBC', ?, ?, ?, ?, ?, NULL, NULL, ?, 'admin-bulk', NULL, ?, 0.72, ?)
                    """,
                    (
                        area["id"],
                        name,
                        venue_slug,
                        venue_type,
                        address,
                        f"Bulk added admin venue for {area['name']}. Details need review.",
                        latitude,
                        longitude,
                        opens_at,
                        closes_at,
                        facebook_url,
                        1 if publish else 0,
                        "admin-reviewed" if publish else "needs-review",
                        now,
                    ),
                ).lastrowid
            saved += 1
        rows.append(
            venue_report_row(
                "saved" if action == "apply" else "ready",
                name,
                f"{venue_type} | {address} | {latitude}, {longitude}",
                facebook_url or None,
                venue_id,
            )
        )

    if action == "apply":
        db.commit()
        flash(f"Bulk venue import saved {saved} venue record(s).", "success")
    else:
        flash(f"Previewed {len(rows)} bulk venue row(s). Nothing was saved yet.", "success")
    set_dashboard_report("Bulk venue import", rows, "Preview rows carefully before saving.")
    return redirect(f"{url_for('nightlife.dashboard', queue='draft-pubs')}#review-queue")


@bp.post("/dashboard/admin-tools/bulk-events")
@login_required(role="admin")
def admin_bulk_events():
    values = require_non_empty_form("event_rows")
    if values is None:
        return redirect(url_for("nightlife.dashboard"))
    action = request_action()
    publish = request.form.get("publish") == "on"
    db = get_db()
    rows = []
    saved = 0
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for line_number, parts in parse_bulk_lines(values["event_rows"]):
        if len(parts) < 6:
            rows.append(event_report_row("error", f"Line {line_number}", "Use: venue slug | title | start | end | genre | description | price | source url"))
            continue
        venue_slug, title, start_at, end_at, genre, description = parts[:6]
        price_label = parts[6] if len(parts) > 6 and parts[6] else "TBC"
        source_url = parts[7] if len(parts) > 7 else ""
        venue = db.execute("SELECT id, name, is_published FROM venues WHERE slug = ?", (venue_slug,)).fetchone()
        if venue is None:
            rows.append(event_report_row("error", title or f"Line {line_number}", f"Venue slug not found: {venue_slug}", source_url or None))
            continue
        if not title or not start_at or not end_at or not genre or not description:
            rows.append(event_report_row("error", f"Line {line_number}", "Title, start, end, genre, and description are required.", source_url or None))
            continue
        price_amount = None
        if price_label.lower().startswith(("€", "eur")):
            price_amount = parse_optional_float(price_label.lower().replace("eur", "").replace("€", ""))
        event_id = None
        if action == "apply":
            existing = db.execute(
                "SELECT id FROM events WHERE venue_id = ? AND LOWER(title) = LOWER(?) AND start_at = ?",
                (venue["id"], title, start_at),
            ).fetchone()
            if existing:
                event_id = existing["id"]
                db.execute(
                    """
                    UPDATE events
                    SET description = ?, genre = ?, end_at = ?, price_label = ?, price_amount = ?,
                        is_published = ?, source_type = ?, source_url = ?, sync_status = ?, confidence = ?, last_verified_at = ?
                    WHERE id = ?
                    """,
                    (
                        description,
                        genre,
                        end_at,
                        price_label,
                        price_amount,
                        1 if publish else 0,
                        "admin-bulk",
                        source_url,
                        "admin-reviewed" if publish else "needs-review",
                        0.76,
                        now,
                        event_id,
                    ),
                )
            else:
                event_id = db.execute(
                    """
                    INSERT INTO events
                    (
                        venue_id, title, description, genre, start_at, end_at, price_label, price_amount,
                        image_url, currency, is_published, source_type, source_url, sync_status, confidence, last_verified_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'EUR', ?, 'admin-bulk', ?, ?, 0.76, ?)
                    """,
                    (
                        venue["id"],
                        title,
                        description,
                        genre,
                        start_at,
                        end_at,
                        price_label,
                        price_amount,
                        1 if publish else 0,
                        source_url,
                        "admin-reviewed" if publish else "needs-review",
                        now,
                    ),
                ).lastrowid
            saved += 1
        rows.append(
            event_report_row(
                "saved" if action == "apply" else "ready",
                f"{title} | {venue['name']}",
                f"{start_at} | {genre} | {price_label}",
                source_url or None,
                event_id,
            )
        )

    if action == "apply":
        db.commit()
        flash(f"Bulk event import saved {saved} event record(s).", "success")
    else:
        flash(f"Previewed {len(rows)} bulk event row(s). Nothing was saved yet.", "success")
    set_dashboard_report("Bulk event import", rows, "Preview rows carefully before saving.")
    return redirect(f"{url_for('nightlife.dashboard', queue='draft-events')}#review-queue")


@bp.post("/dashboard/admin-tools/delete-old-events")
@login_required(role="admin")
def admin_delete_old_events():
    values = require_non_empty_form("before_date")
    if values is None:
        return redirect(url_for("nightlife.dashboard"))
    action = request_action()
    before_date = values["before_date"]
    scope = request.form.get("scope", "all").strip()
    if scope not in {"all", "drafts", "published"}:
        abort(400)
    where = ["date(e.start_at) < date(?)"]
    params = [before_date]
    if scope == "drafts":
        where.append("e.is_published = 0")
    elif scope == "published":
        where.append("e.is_published = 1")
    where_sql = " AND ".join(where)
    db = get_db()
    matches = db.execute(
        f"""
        SELECT e.id, e.title, e.start_at, e.source_url, v.name AS venue_name
        FROM events e
        JOIN venues v ON v.id = e.venue_id
        WHERE {where_sql}
        ORDER BY e.start_at ASC
        LIMIT 80
        """,
        params,
    ).fetchall()
    total = db.execute(f"SELECT COUNT(*) AS count FROM events e WHERE {where_sql}", params).fetchone()["count"]
    if action == "apply" and request.form.get("confirm_delete") != "on":
        flash("Tick the confirmation checkbox before deleting old events.", "error")
        action = "preview"
    rows = [
        event_report_row(
            "ready" if action == "preview" else "saved",
            f"{event['title']} | {event['venue_name']}",
            f"Starts {event['start_at']}",
            event["source_url"],
            event["id"],
        )
        for event in matches
    ]
    if action == "apply":
        db.execute(f"DELETE FROM events WHERE id IN (SELECT e.id FROM events e WHERE {where_sql})", params)
        db.commit()
        flash(f"Deleted {total} old event record(s).", "success")
        rows = [event_report_row("saved", "Old events deleted", f"Deleted {total} event(s) before {before_date}.")]
    else:
        flash(f"Previewed {min(total, 80)} of {total} old event(s). Nothing was deleted yet.", "success")
    set_dashboard_report("Old event cleanup", rows, f"Scope: {scope}. Cutoff date: {before_date}.")
    return redirect(f"{url_for('nightlife.dashboard', queue='draft-events')}#review-queue")


@bp.post("/dashboard/admin-tools/bulk-venue-action")
@login_required(role="admin")
def admin_bulk_venue_action():
    venue_ids = selected_int_ids("venue_ids")
    action = request.form.get("bulk_action", "").strip()
    if action not in {"publish", "unpublish", "review"}:
        abort(400)
    if not venue_ids:
        flash("Select at least one pub before applying a bulk action.", "error")
        return dashboard_redirect()

    now = datetime.now(UTC).isoformat(timespec="seconds")
    placeholders = ",".join("?" for _ in venue_ids)
    if action == "publish":
        sql = f"UPDATE venues SET is_published = 1, sync_status = ?, last_verified_at = ? WHERE id IN ({placeholders})"
        params = ["admin-approved", now, *venue_ids]
        message = "Published"
    elif action == "unpublish":
        sql = f"UPDATE venues SET is_published = 0, sync_status = ?, last_verified_at = ? WHERE id IN ({placeholders})"
        params = ["admin-unpublished", now, *venue_ids]
        message = "Unpublished"
    else:
        sql = f"UPDATE venues SET sync_status = ?, last_verified_at = ? WHERE id IN ({placeholders})"
        params = ["admin-reviewed", now, *venue_ids]
        message = "Marked reviewed"

    db = get_db()
    db.execute(sql, params)
    db.commit()
    flash(f"{message} {len(venue_ids)} selected pub record(s).", "success")
    if action == "publish":
        return dashboard_queue_redirect("published")
    if action == "unpublish":
        return dashboard_queue_redirect("draft-pubs")
    return dashboard_redirect()


@bp.post("/dashboard/admin-tools/bulk-event-action")
@login_required(role="admin")
def admin_bulk_event_action():
    event_ids = selected_int_ids("event_ids")
    action = request.form.get("bulk_action", "").strip()
    if action not in {"publish", "unpublish", "review", "delete"}:
        abort(400)
    if not event_ids:
        flash("Select at least one event before applying a bulk action.", "error")
        return dashboard_redirect()
    if action == "delete" and request.form.get("confirm_delete") != "on":
        flash("Tick the confirmation checkbox before deleting selected events.", "error")
        return dashboard_redirect()

    now = datetime.now(UTC).isoformat(timespec="seconds")
    placeholders = ",".join("?" for _ in event_ids)
    db = get_db()
    if action == "publish":
        db.execute(f"UPDATE events SET is_published = 1, sync_status = ?, last_verified_at = ? WHERE id IN ({placeholders})", ["admin-approved", now, *event_ids])
        message = "Published"
    elif action == "unpublish":
        db.execute(f"UPDATE events SET is_published = 0, sync_status = ?, last_verified_at = ? WHERE id IN ({placeholders})", ["admin-unpublished", now, *event_ids])
        message = "Unpublished"
    elif action == "review":
        db.execute(f"UPDATE events SET sync_status = ?, last_verified_at = ? WHERE id IN ({placeholders})", ["admin-reviewed", now, *event_ids])
        message = "Marked reviewed"
    else:
        db.execute(f"DELETE FROM events WHERE id IN ({placeholders})", event_ids)
        message = "Deleted"
    db.commit()
    flash(f"{message} {len(event_ids)} selected event record(s).", "success")
    if action == "publish":
        return dashboard_queue_redirect("published")
    if action in {"unpublish", "delete"}:
        return dashboard_queue_redirect("draft-events")
    return dashboard_redirect()


@bp.post("/dashboard/admin-tools/apify-events")
@login_required(role="admin")
def admin_apify_event_sync():
    values = require_non_empty_form("area")
    if values is None:
        return redirect(url_for("nightlife.dashboard"))
    action = request_action()
    token = env_value("APIFY_API_TOKEN")
    if not token:
        flash("APIFY_API_TOKEN is missing. Add it to your environment before syncing Facebook events.", "error")
        return redirect(url_for("nightlife.dashboard"))

    posts_per_page = parse_positive_int("posts_per_page", 5, 25)
    newer_than = request.form.get("newer_than", "3 months").strip() or "3 months"
    venue_slug = request.form.get("venue_slug", "").strip() or None
    skip_past = request.form.get("skip_past") == "on"
    publish = request.form.get("publish") == "on"
    no_ai_cleanup = request.form.get("no_ai_cleanup") == "on"

    try:
        venues = load_facebook_venues(values["area"], venue_slug)
    except Exception as exc:
        flash(f"Could not load Facebook venues: {exc}", "error")
        return redirect(url_for("nightlife.dashboard"))
    if not venues:
        flash("No venues with saved Facebook page URLs were found for that selection.", "error")
        return redirect(url_for("nightlife.dashboard"))

    rows = []
    candidates = []
    imported = 0
    for venue in venues:
        try:
            posts = run_facebook_posts_scraper(token=token, page_url=venue["social_facebook"], results_limit=posts_per_page, newer_than=newer_than)
            events = extract_events_from_posts(posts, venue["name"])
            if skip_past:
                events = [event for event in events if not event_is_past(event.start_at)]
            if not no_ai_cleanup and ai_cleanup_enabled():
                for event in events:
                    try:
                        cleaned = clean_event_with_ai(event.to_dict(), venue["name"], event.post_text, image_url=event.image_url)
                    except requests.RequestException:
                        cleaned = None
                    if cleaned is None:
                        continue
                    event.title = cleaned.title
                    event.description = cleaned.description
                    event.genre = cleaned.genre
                    event.price_label = cleaned.price_label
                    event.price_amount = cleaned.price_amount
                    event.confidence = min(1.0, (event.confidence + cleaned.confidence) / 2)
                    if cleaned.needs_review:
                        event.confidence = min(event.confidence, 0.62)
            for event in events:
                event_id = None
                if action == "apply":
                    if upsert_event(venue["id"], event, publish=publish):
                        imported += 1
                    event_id = event_id_for_sync(venue["id"], event)
                rows.append(
                    event_report_row(
                        "published" if action == "apply" and publish else "saved" if action == "apply" else "ready",
                        f"{event.title} | {venue['name']}",
                        f"{event.start_at} | {event.genre} | confidence {event.confidence:.2f}",
                        event.source_url,
                        event_id,
                    )
                )
                if action == "preview":
                    candidate_id = f"{venue['id']}-{len(candidates)}"
                    candidates.append(
                        {
                            "id": candidate_id,
                            "venue": {"id": venue["id"], "name": venue["name"], "slug": venue["slug"]},
                            "event": event.to_dict(),
                        }
                    )
            if not events:
                rows.append(venue_report_row("no-events", venue["name"], f"Checked {len(posts)} post(s); no event detected.", venue["social_facebook"], venue["id"]))
        except (requests.RequestException, ValueError) as exc:
            rows.append(venue_report_row("error", venue["name"], str(exc), venue["social_facebook"], venue["id"]))

    if action == "apply":
        session.pop("event_candidates", None)
        get_db().commit()
        flash(f"Event sync saved {imported} new event(s). Existing matching events may have been updated.", "success")
    else:
        session["event_candidates"] = candidates
        flash("Event sync preview complete. Nothing was saved yet.", "success")
    set_dashboard_report("Apify event sync", rows, f"Checked {len(venues)} venue page(s).")
    if action == "preview" and candidates:
        return redirect(f"{url_for('nightlife.dashboard', queue='draft-events')}#event-candidates")
    return redirect(url_for("nightlife.dashboard"))


@bp.post("/dashboard/admin-tools/event-candidates")
@login_required(role="admin")
def admin_save_event_candidates():
    candidate_ids = set(request.form.getlist("candidate_id"))
    publish = request.form.get("publish") == "on"
    candidates = dashboard_event_candidates()
    if not candidate_ids:
        flash("Select at least one event candidate to save.", "error")
        return redirect(f"{url_for('nightlife.dashboard', queue='draft-events')}#event-candidates")

    rows = []
    saved = 0
    remaining = []
    for candidate in candidates:
        event_data = candidate.get("event") or {}
        venue = candidate.get("venue") or {}
        candidate_id = candidate.get("id")
        if candidate_id not in candidate_ids:
            remaining.append(candidate)
            continue
        venue_id = venue.get("id")
        if not venue_id:
            rows.append(event_report_row("error", event_data.get("title", "Unknown event"), "Missing venue ID", event_data.get("source_url")))
            continue
        event = FacebookPostEvent(**event_data)
        if upsert_event(int(venue_id), event, publish=publish):
            saved += 1
        event_id = event_id_for_sync(int(venue_id), event)
        rows.append(
            event_report_row(
                "published" if publish else "saved",
                f"{event.title} | {venue.get('name', 'Unknown venue')}",
                f"{event.start_at} | {event.genre} | confidence {event.confidence:.2f}",
                event.source_url,
                event_id,
            )
        )

    get_db().commit()
    session["event_candidates"] = remaining
    flash(f"Saved {len(candidate_ids)} selected event candidate(s). {saved} were new; matching events may have been updated.", "success")
    set_dashboard_report("Selected event candidates saved", rows, "Only checked candidates were saved.")
    return redirect(f"{url_for('nightlife.dashboard', queue='draft-events')}#event-candidates")


@bp.post("/dashboard/admin-tools/event-candidates/clear")
@login_required(role="admin")
def admin_clear_event_candidates():
    session.pop("event_candidates", None)
    flash("Cleared the event candidate preview inbox.", "success")
    return redirect(f"{url_for('nightlife.dashboard', queue='draft-events')}#review-queue")


@bp.post("/dashboard/admin-tools/publish-venue/<int:venue_id>")
@login_required(role="admin")
def admin_publish_venue(venue_id):
    db = get_db()
    venue = db.execute("SELECT id, name FROM venues WHERE id = ?", (venue_id,)).fetchone()
    if venue is None:
        abort(404)
    db.execute(
        "UPDATE venues SET is_published = 1, sync_status = ?, last_verified_at = ? WHERE id = ?",
        ("admin-approved", datetime.now(UTC).isoformat(timespec="seconds"), venue_id),
    )
    db.commit()
    flash(f"Published {venue['name']} to the public website.", "success")
    set_dashboard_report("Venue published", [venue_report_row("published", venue["name"], "Approved for public display", None, venue_id)])
    return dashboard_redirect()


@bp.post("/dashboard/admin-tools/unpublish-venue/<int:venue_id>")
@login_required(role="admin")
def admin_unpublish_venue(venue_id):
    db = get_db()
    venue = db.execute("SELECT id, name FROM venues WHERE id = ?", (venue_id,)).fetchone()
    if venue is None:
        abort(404)
    db.execute(
        "UPDATE venues SET is_published = 0, sync_status = ?, last_verified_at = ? WHERE id = ?",
        ("admin-unpublished", datetime.now(UTC).isoformat(timespec="seconds"), venue_id),
    )
    db.commit()
    flash(f"Unpublished {venue['name']} from the public website.", "success")
    return dashboard_redirect()


@bp.post("/dashboard/admin-tools/review-venue/<int:venue_id>")
@login_required(role="admin")
def admin_review_venue(venue_id):
    db = get_db()
    venue = db.execute("SELECT id, name FROM venues WHERE id = ?", (venue_id,)).fetchone()
    if venue is None:
        abort(404)
    db.execute(
        "UPDATE venues SET sync_status = ?, last_verified_at = ? WHERE id = ?",
        ("admin-reviewed", datetime.now(UTC).isoformat(timespec="seconds"), venue_id),
    )
    db.commit()
    flash(f"Marked {venue['name']} as reviewed.", "success")
    return dashboard_redirect()


@bp.post("/dashboard/admin-tools/publish-event/<int:event_id>")
@login_required(role="admin")
def admin_publish_event(event_id):
    db = get_db()
    event = db.execute(
        """
        SELECT e.id, e.title, v.name AS venue_name, v.is_published AS venue_published
        FROM events e
        JOIN venues v ON v.id = e.venue_id
        WHERE e.id = ?
        """,
        (event_id,),
    ).fetchone()
    if event is None:
        abort(404)
    if not event["venue_published"]:
        flash("Publish the venue first before publishing its events.", "error")
        return redirect(url_for("nightlife.dashboard"))
    db.execute(
        "UPDATE events SET is_published = 1, sync_status = ?, last_verified_at = ? WHERE id = ?",
        ("admin-approved", datetime.now(UTC).isoformat(timespec="seconds"), event_id),
    )
    db.commit()
    flash(f"Published {event['title']} at {event['venue_name']}.", "success")
    set_dashboard_report("Event published", [event_report_row("published", event["title"], f"Approved at {event['venue_name']}", None, event_id)])
    return dashboard_redirect()


@bp.post("/dashboard/admin-tools/unpublish-event/<int:event_id>")
@login_required(role="admin")
def admin_unpublish_event(event_id):
    db = get_db()
    event = db.execute("SELECT id, title FROM events WHERE id = ?", (event_id,)).fetchone()
    if event is None:
        abort(404)
    db.execute(
        "UPDATE events SET is_published = 0, sync_status = ?, last_verified_at = ? WHERE id = ?",
        ("admin-unpublished", datetime.now(UTC).isoformat(timespec="seconds"), event_id),
    )
    db.commit()
    flash(f"Unpublished {event['title']} from the public website.", "success")
    return dashboard_redirect()


@bp.post("/dashboard/admin-tools/review-event/<int:event_id>")
@login_required(role="admin")
def admin_review_event(event_id):
    db = get_db()
    event = db.execute("SELECT id, title FROM events WHERE id = ?", (event_id,)).fetchone()
    if event is None:
        abort(404)
    db.execute(
        "UPDATE events SET sync_status = ?, last_verified_at = ? WHERE id = ?",
        ("admin-reviewed", datetime.now(UTC).isoformat(timespec="seconds"), event_id),
    )
    db.commit()
    flash(f"Marked {event['title']} as reviewed.", "success")
    return dashboard_redirect()


@bp.post("/dashboard/claims/<int:claim_id>")
@login_required(role="admin")
def review_claim(claim_id):
    status = request.form.get("status", "pending")
    if status not in {"approved", "rejected", "pending"}:
        abort(400)
    db = get_db()
    claim = db.execute(
        """
        SELECT vc.id, vc.status, v.name AS venue_name
        FROM venue_claims vc
        JOIN venues v ON v.id = vc.venue_id
        WHERE vc.id = ?
        """,
        (claim_id,),
    ).fetchone()
    if claim is None:
        abort(404)
    db.execute("UPDATE venue_claims SET status = ? WHERE id = ?", (status, claim_id))
    db.commit()
    action_label = "approved" if status == "approved" else "rejected" if status == "rejected" else "marked as pending"
    flash(f"Claim for {claim['venue_name']} {action_label}.", "success")
    return redirect(f"{url_for('nightlife.dashboard')}#venue-claims")
