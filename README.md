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

Open `http://127.0.0.1:5000`.

Demo logins:

- `admin / adminpass`
- `velvet_owner / ownerpass`

## Test

```powershell
cd C:\Users\Admin\Documents\town-nightlife-finder
python -m unittest discover -s tests
```
