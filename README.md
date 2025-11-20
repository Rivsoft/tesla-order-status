# Tesla Order Status Dashboard

A self-hosted FastAPI application that surfaces the latest data from your Tesla order. It renders a polished dashboard with VIN metadata, delivery blockers, task progress, and raw payload details so you can track the journey from reservation to delivery without refreshing the Tesla app.

> **Heads-up:** This project is not affiliated with Tesla. It uses your own session tokens to call the publicly available Owner API. Treat the exported data with the same care as any other personal information.

---

## Table of Contents
- [Tesla Order Status Dashboard](#tesla-order-status-dashboard)
  - [Table of Contents](#table-of-contents)
  - [Highlights](#highlights)
  - [Architecture](#architecture)
  - [Prerequisites](#prerequisites)
  - [Running Locally with Poetry](#running-locally-with-poetry)
  - [Authenticating with Tesla](#authenticating-with-tesla)
  - [Refreshing \& Cached Data](#refreshing--cached-data)
  - [Utilities](#utilities)
  - [Project Layout](#project-layout)
  - [Troubleshooting](#troubleshooting)
  - [Contributing](#contributing)

---

## Highlights
- **Rich dashboard** – responsive cards with VIN image carousel, decoded VIN modal, delivery blockers, and order task timelines.
- **Insight extraction** – delivery, finance, registration, and metadata panels sourced from the Tesla Owner API payload.
- **Reusable modal system** – VIN decode details are available on-demand instead of dumping everything into the main grid.
- **Multi-run caching** – API responses and tokens are stored on disk (`tesla_orders.json`, `tesla_tokens.json`) so the UI can render instantly at startup.
- **True dark theme** – minimal motion and color-coded states for quick scanning.

---

## Architecture
- **FastAPI** (`app/main.py`) serves HTML views using Jinja2 templates and exposes `/`, `/login`, `/refresh`, and `/history` routes.
- **Monitor service** (`app/monitor.py`) manages Tesla OAuth tokens, calls the Owner API, and normalizes the nested JSON structure into UI-friendly dictionaries.
- **VIN decoder** (`app/vin_decoder.py`) provides offline decoding for the assigned VIN so you can see motor, factory, and battery details.
- **Templates** (`app/templates/`) implement the entire UI layer. No frontend build tooling is required; styling relies on utility classes defined in the base template.

---

## Prerequisites
- Tesla account with an active order (needed to complete the OAuth flow).
- **Python 3.11+** with [Poetry](https://python-poetry.org/) for dependency management.
- Two writable files in the project root:
  - `tesla_tokens.json` – stores access + refresh tokens.
  - `tesla_orders.json` – stores the most recent Owner API payload.

Both files are already gitignored. If they do not exist yet, create them before starting the app:

```powershell
# Windows PowerShell
ni tesla_tokens.json -ItemType File
ni tesla_orders.json -ItemType File
```

```bash
# macOS/Linux
touch tesla_tokens.json tesla_orders.json
```

---

## Running Locally with Poetry
1. Install Poetry (once):
   ```bash
   pip install poetry
   ```
2. Install dependencies:
   ```bash
   poetry install
   ```
3. Launch FastAPI in autoreload mode:
   ```bash
   poetry run uvicorn app.main:app --reload
   ```
4. Visit [http://localhost:8000](http://localhost:8000).

Use `poetry run uvicorn app.main:app --reload --port 9000` if you need a different port.

---

## Authenticating with Tesla
1. Navigate to `/login`.
2. Click **Open Tesla Login** – a new tab will load `auth.tesla.com`.
3. Complete the login; Tesla will redirect you to `https://auth.tesla.com/void/callback?...` and show a "Page Not Found" message.
4. Copy the entire callback URL from the browser address bar.
5. Paste it into the form on `/login` and submit.

The server stores the access + refresh tokens in `tesla_tokens.json`. You can revoke access from your Tesla account at any time; just delete the JSON file locally to force a new login.

---

## Refreshing & Cached Data
- The dashboard reads `tesla_orders.json` first, so a previous snapshot appears instantly.
- Click **Refresh Orders** (or load `/refresh`) to fetch fresh data. The new payload replaces the cached JSON on disk.
- Each order card still shows the raw payload inside a collapsible block in case you want to inspect the original Tesla response.

---

## Utilities
| Tool | Command | Description |
| ---- | ------- | ----------- |
| VIN decoder regression | `poetry run python scripts/validate_vin_decoder.py` | Calls NHTSA's VPIC API for several sample VINs and compares the results with the bundled decoder output. Requires an internet connection. |

---

## Project Layout
```
app/
  __init__.py
  main.py            # FastAPI entrypoint & routes
  monitor.py         # Tesla API client + caching helpers
  tesla_stores.py    # Enum of routing locations
  vin_decoder.py     # Offline VIN metadata decoder
  templates/
    base.html
    index.html
    login.html
    history.html
README.md
poetry.lock
pyproject.toml
scripts/
  validate_vin_decoder.py
```

---

## Troubleshooting
- **Redirect loop to /login** – make sure `tesla_tokens.json` exists and is writable by the server/container user.
- **401 or rate limiting errors** – tokens may be expired or revoked. Delete `tesla_tokens.json` and repeat the login flow.
- **VIN modal renders off-screen** – ensure you are loading the bundled CSS (no CDN dependency) and check the browser console for blocking extensions.
- **Changes not visible** – restart the Poetry-run Uvicorn server after editing templates or Python modules.

---

## Contributing
Issues and pull requests are welcome. If you add new Tesla API calls, please avoid committing personal data and update this README so others understand the new behavior.

