# Deploy Town Nightlife Finder on Render

This project is prepared for a Render test deployment using Docker, Flask, Gunicorn, SQLite on a persistent disk, and a Vite frontend build.

## Why this setup

- Docker builds the React/Vite frontend during deployment.
- Docker installs Tesseract so OCR can work for Facebook post images.
- Render's persistent disk stores the SQLite database at `/data/nightlife.db`.
- `gunicorn` runs Flask in production mode.

This is a good public testing setup. For heavier production usage, migrate the database from SQLite to PostgreSQL later.

## Files used by Render

- `render.yaml` provisions the Render web service and persistent disk.
- `Dockerfile` builds the frontend and backend runtime.
- `.dockerignore` keeps local databases, virtual environments, and secrets out of the Docker image.
- `Procfile` remains available for non-Docker hosts, but Render will use the Dockerfile.

## Deploy steps

1. Push this project to GitHub.
2. Log in to Render.
3. Choose **New > Blueprint**.
4. Connect the GitHub repo.
5. Render should detect `render.yaml`.
6. Add these secret environment variables when Render asks:

```text
GOOGLE_MAPS_API_KEY
APIFY_API_TOKEN
OPENAI_API_KEY
```

`SECRET_KEY`, `DATABASE_URL`, `FLASK_DEBUG`, `OSRM_BASE_URL`, and `OPENAI_EVENT_CLEANUP_MODEL` are already defined in `render.yaml`.

## First checks after deploy

Open these URLs:

```text
https://your-render-url.onrender.com/health
https://your-render-url.onrender.com/
https://your-render-url.onrender.com/login
https://your-render-url.onrender.com/dashboard
```

The `/health` route should return:

```json
{"ok": true}
```

## Important security steps before sharing

- Change the demo admin password before inviting testers.
- Keep `.env` out of GitHub.
- Restrict Google API keys in Google Cloud.
- Monitor Apify/OpenAI usage because scraping and AI cleanup can cost money.
- Use HTTPS only, which Render provides automatically.

## Database note

The Render test deployment uses SQLite at:

```text
/data/nightlife.db
```

That path lives on the attached Render persistent disk. Do not set `DATABASE_URL` to `nightlife.db` on Render, or data may be lost on redeploy.
