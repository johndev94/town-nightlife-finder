import os
from pathlib import Path
from datetime import UTC, datetime
from functools import wraps

import requests
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for
from flask import current_app

from app.ai_event_cleaner import ai_cleanup_enabled, clean_event_with_ai
from app.apify_facebook import extract_events_from_posts, run_facebook_posts_scraper
from app.facebook_page_discovery import best_confident_candidate, discover_facebook_page_candidates
from app.google_places import GooglePlacesClient, ensure_google_place_columns, load_env_file

from import_ballina_google_places import area_slug_for, collect_places, fetch_or_create_area, load_town_bounds, upsert_place
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


def set_dashboard_report(title, rows, summary=None):
    session["dashboard_report"] = {
        "title": title,
        "summary": summary or "",
        "rows": rows[:80],
    }


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
    if user["role"] == "admin":
        venues = db.execute("SELECT v.*, a.name AS area_name FROM venues v JOIN areas a ON a.id = v.area_id ORDER BY a.name, v.name").fetchall()
        areas = db.execute("SELECT * FROM areas ORDER BY name").fetchall()
        claims = db.execute("SELECT vc.*, v.name AS venue_name FROM venue_claims vc JOIN venues v ON v.id = vc.venue_id ORDER BY vc.created_at DESC").fetchall()
    else:
        venues = db.execute("SELECT v.*, a.name AS area_name FROM venues v JOIN areas a ON a.id = v.area_id WHERE v.claimed_by_user_id = ? ORDER BY v.name", (user["id"],)).fetchall()
        areas = []
        claims = []
    events = []
    if venues:
        ids = [venue["id"] for venue in venues]
        query = ",".join("?" for _ in ids)
        events = db.execute(f"SELECT e.*, v.name AS venue_name FROM events e JOIN venues v ON v.id = e.venue_id WHERE e.venue_id IN ({query}) ORDER BY e.start_at ASC", ids).fetchall()
    return render_template("dashboard.html", user=user, venues=venues, events=events, claims=claims, areas=areas, admin_report=dashboard_report())


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
    return redirect(url_for("nightlife.dashboard"))


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
    return redirect(url_for("nightlife.dashboard"))


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
        {
            "status": "ready" if action == "preview" else "saved",
            "primary": place.name,
            "secondary": f"{place.inferred_type} | {place.address}",
            "url": place.google_maps_uri,
        }
        for place in places
    ]

    inserted = updated = 0
    if action == "apply" and places:
        db = get_db()
        ensure_google_place_columns(db)
        area = fetch_or_create_area(db, values["town"], values["county"], area_slug, places, True, bounds)
        for place in places:
            result = upsert_place(db, area["id"], values["town"], place)
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
            rows.append({"status": "error", "primary": venue["name"], "secondary": str(exc), "url": None})
            continue

        selected = best_confident_candidate(candidates, min_score=min_score, min_gap=min_gap)
        if selected and action == "apply":
            db.execute("UPDATE venues SET social_facebook = ?, last_verified_at = ? WHERE id = ?", (selected.url, datetime.now(UTC).isoformat(timespec="seconds"), venue["id"]))
            applied += 1
        top = selected or (candidates[0] if candidates else None)
        rows.append(
            {
                "status": "saved" if selected and action == "apply" else "ready" if selected else "needs-review" if candidates else "no-match",
                "primary": venue["name"],
                "secondary": f"Score {top.score:.2f}: {top.title}" if top else "No likely Facebook page found",
                "url": top.url if top else None,
            }
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
    set_dashboard_report("Manual Facebook page update", [{"status": "saved", "primary": venue["name"], "secondary": "Official profile link saved", "url": values["social_facebook"]}])
    return redirect(url_for("nightlife.dashboard"))


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
                if action == "apply" and upsert_event(venue["id"], event, publish=publish):
                    imported += 1
                rows.append(
                    {
                        "status": "published" if action == "apply" and publish else "saved" if action == "apply" else "ready",
                        "primary": f"{event.title} | {venue['name']}",
                        "secondary": f"{event.start_at} | {event.genre} | confidence {event.confidence:.2f}",
                        "url": event.source_url,
                    }
                )
            if not events:
                rows.append({"status": "no-events", "primary": venue["name"], "secondary": f"Checked {len(posts)} post(s); no event detected.", "url": venue["social_facebook"]})
        except (requests.RequestException, ValueError) as exc:
            rows.append({"status": "error", "primary": venue["name"], "secondary": str(exc), "url": venue["social_facebook"]})

    if action == "apply":
        get_db().commit()
        flash(f"Event sync saved {imported} new event(s). Existing matching events may have been updated.", "success")
    else:
        flash("Event sync preview complete. Nothing was saved yet.", "success")
    set_dashboard_report("Apify event sync", rows, f"Checked {len(venues)} venue page(s).")
    return redirect(url_for("nightlife.dashboard"))


@bp.post("/dashboard/claims/<int:claim_id>")
@login_required(role="admin")
def review_claim(claim_id):
    status = request.form.get("status", "pending")
    if status not in {"approved", "rejected", "pending"}:
        abort(400)
    db = get_db()
    claim = db.execute("SELECT id FROM venue_claims WHERE id = ?", (claim_id,)).fetchone()
    if claim is None:
        abort(404)
    db.execute("UPDATE venue_claims SET status = ? WHERE id = ?", (status, claim_id))
    db.commit()
    flash(f"Claim marked as {status}.", "success")
    return redirect(url_for("nightlife.dashboard"))
