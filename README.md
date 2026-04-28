# Town Nightlife Finder

A mobile-first nightlife MVP with a React + TypeScript frontend served by a Flask + SQLite backend.

## Features

- Public venue and event discovery built in React + TypeScript
- Area-based discovery, genre/price/open-now filters, and venue detail views
- Venue detail pages with hours, social links, source freshness, and claim requests
- JSON APIs for areas, venues, events, and venue detail
- Admin and venue-owner dashboards for keeping listings fresh

## Run locally

```powershell
cd C:\Users\Admin\Documents\town-nightlife-finder
python run.py
```

The app now listens on `0.0.0.0:5000` by default, so it is reachable from your LAN and can be exposed through your router.

Open locally at `http://127.0.0.1:5000` or from another device on your network at `http://<your-lan-ip>:5000`.

You can override the bind address, port, and debug mode:

```powershell
$env:FLASK_RUN_HOST="0.0.0.0"
$env:FLASK_RUN_PORT="8080"
$env:FLASK_DEBUG="0"
python run.py
```

## Expose to the web

1. Allow inbound TCP traffic to the app port in Windows Firewall.
2. Port forward your chosen external port on the router to this PC's LAN IP and the same internal port.
3. Browse to `http://<your-public-ip>:<forwarded-port>`.

Example firewall command for port `5000`:

```powershell
New-NetFirewallRule -DisplayName "Town Nightlife Finder 5000" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow
```

Important: this is Flask's built-in development server, so it is fine for testing from the internet but not a hardened production deployment. If you want, I can also set this up behind Waitress or Nginx next.

Demo logins:

- `admin / adminpass`
- `velvet_owner / ownerpass`

## Test

```powershell
cd C:\Users\Admin\Documents\town-nightlife-finder
python -m unittest discover -s tests
```

## Scraper Starter

There is now a first-pass scraper for venue websites and official source pages.

It currently:

- pulls `source_url` values from published venues
- skips unsupported social platforms such as Facebook and Instagram
- extracts events from `application/ld+json` when a site exposes Schema.org `Event` data
- falls back to simple page-content heuristics for event cards and listings
- emits a JSON report instead of writing directly into the database

Run it like this:

```powershell
cd C:\Users\Admin\Documents\town-nightlife-finder
python scrape_sources.py --limit 10
```

Scrape just one area:

```powershell
python scrape_sources.py --area ballina-town
```

Save results to a file:

```powershell
python scrape_sources.py --output scraped-events.json
```

Target one venue:

```powershell
python scrape_sources.py --slug the-lantern-arms
```

## Ballina Starter Data

You can seed a first real-world starter set for Ballina, Co. Mayo, Ireland with:

```powershell
cd C:\Users\Admin\Documents\town-nightlife-finder
python seed_ballina.py
```

This adds a `ballina-town` area plus starter venue/source records including:

- Bar Square Ballina
- Paddy Mac's Ballina
- McShane's Bar Ballina
- The Merry Monk

To add a real dated Ballina event plus review placeholders:

```powershell
python seed_ballina_events.py
```

Important: this starter is intentionally compliant-first. It does not do unofficial scraping of Facebook, Instagram, TikTok, or similar platforms. The next step would be a review/import workflow that lets you approve scraped events before updating the database.

## Google Places Venue Location Correction

You can use Google Places to correct venue addresses and map coordinates.

1. Create a Google Cloud API key with the Places API enabled.
2. Add the key to a local `.env` file:

```powershell
GOOGLE_MAPS_API_KEY=your_google_maps_api_key_here
```

Preview Google matches without changing the database:

```powershell
python geocode_venues_google.py --area ballina-town
```

Apply corrections after reviewing the preview:

```powershell
python geocode_venues_google.py --area ballina-town --apply
```

Correct a single venue:

```powershell
python geocode_venues_google.py --slug bar-square-ballina --apply
```

Manually correct a venue when Google returns the wrong match:

```powershell
python geocode_venues_google.py --slug bar-square-ballina --manual-lat 54.114658 --manual-lng -9.157807 --manual-address "Garden Street, Ballina, Co. Mayo, Ireland" --apply
```

Useful options:

- `--min-score 0.72` only applies stronger matches.
- `--no-address-update` updates coordinates and Google metadata but keeps your existing address text.
- `--limit 3` checks only the first few venues while testing.

This command uses Google Places Text Search with a limited field mask for place ID, display name, formatted address, coordinates, Google Maps URL, and business status.
