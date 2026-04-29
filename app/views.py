from datetime import UTC, datetime
from functools import wraps

import requests
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for
from flask import current_app

from .db import get_db


bp = Blueprint("nightlife", __name__)


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT id, username, role, venue_id FROM users WHERE id = ?", (user_id,)).fetchone()


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
        claims = db.execute("SELECT vc.*, v.name AS venue_name FROM venue_claims vc JOIN venues v ON v.id = vc.venue_id ORDER BY vc.created_at DESC").fetchall()
    else:
        venues = db.execute("SELECT v.*, a.name AS area_name FROM venues v JOIN areas a ON a.id = v.area_id WHERE v.claimed_by_user_id = ? ORDER BY v.name", (user["id"],)).fetchall()
        claims = []
    events = []
    if venues:
        ids = [venue["id"] for venue in venues]
        query = ",".join("?" for _ in ids)
        events = db.execute(f"SELECT e.*, v.name AS venue_name FROM events e JOIN venues v ON v.id = e.venue_id WHERE e.venue_id IN ({query}) ORDER BY e.start_at ASC", ids).fetchall()
    return render_template("dashboard.html", user=user, venues=venues, events=events, claims=claims)


@bp.post("/dashboard/venues/<int:venue_id>")
@login_required()
def update_venue(venue_id):
    user = current_user()
    if not can_manage_venue(user, venue_id):
        abort(403)
    get_db().execute(
        "UPDATE venues SET opens_at = ?, closes_at = ?, price_band = ?, source_type = ?, source_url = ?, sync_status = ?, confidence = ?, last_verified_at = ? WHERE id = ?",
        (
            request.form.get("opens_at", "").strip(),
            request.form.get("closes_at", "").strip(),
            request.form.get("price_band", "").strip(),
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
