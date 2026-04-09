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
