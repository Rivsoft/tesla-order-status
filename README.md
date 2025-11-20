# Tesla Order Status Dashboard

A self-hosted FastAPI application that surfaces the latest data from your Tesla order. It renders a polished dashboard with VIN metadata, delivery blockers, task progress, and raw payload details so you can track the journey from reservation to delivery without refreshing the Tesla app.

> **Heads-up:** This project is not affiliated with Tesla. It uses your own session tokens to call the publicly available Owner API. Treat the exported data with the same care as any other personal information.

---

## Table of Contents
- [Tesla Order Status Dashboard](#tesla-order-status-dashboard)
  - [Table of Contents](#table-of-contents)
  - [Highlights](#highlights)
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
- **Client-held tokens** – OAuth tokens live inside the user's browser (IndexedDB + service worker headers) so the server never stores reusable credentials.
- **Local snapshot history** – the `/history` view keeps browser-only snapshots with diff summaries and scrollable raw payload panels for deep dives without blowing up the layout.
- **True dark theme** – minimal motion and color-coded states for quick scanning.

---

- **FastAPI** (`app/main.py`) serves HTML views using Jinja2 templates and exposes `/`, `/login`, `/refresh`, and `/history` routes. Pages only render when a valid Tesla token bundle is supplied via a custom header.
- **Monitor service** (`app/monitor.py`) manages Tesla OAuth flows, refreshes tokens on the fly, and normalizes the nested JSON structure into UI-friendly dictionaries.
- **VIN decoder** (`app/vin_decoder.py`) provides offline decoding for the assigned VIN so you can see motor, factory, and battery details.
- **Service worker** (`app/static/sw.js`) injects the opaque token bundle into every backend request and persists updates back to IndexedDB, creating a transparent privacy-preserving proxy.
- **Templates** (`app/templates/`) implement the UI while client-side scripts capture history snapshots in `localStorage`.

---

## Prerequisites
- Tesla account with an active order (needed to complete the OAuth flow).
- **Python 3.11+** with [Poetry](https://python-poetry.org/) for dependency management.

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

The callback response stores the access + refresh token bundle inside your browser's IndexedDB, registers the service worker, and immediately redirects back to the dashboard. Tokens never persist on the server. Use **Logout** (or revoke the token inside your Tesla account) to wipe the client-side store at any time.

---

## Refreshing & Cached Data
- Every dashboard load sends your locally stored token bundle to FastAPI, which in turn calls Tesla's Owner API just for that request—no shared server cache exists.
- Click **Refresh Orders** (or load `/refresh`) to trigger a brand-new API call and surface a success banner. Your browser also stores snapshots in `localStorage` so the `/history` page can highlight changes without leaking data to the server.
- Each order card still shows the raw payload inside a collapsible block in case you want to inspect the original Tesla response.
- The `/history` page mirrors that payload with a toggleable, scrollable viewer plus change summaries so you can diff snapshots without leaving the browser.

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
    callback_success.html
    logout.html
  static/
    sw.js            # Service worker that injects token headers
    js/
      app-init.js
      sw-register.js
      token-storage.js
README.md
poetry.lock
pyproject.toml
scripts/
  validate_vin_decoder.py
```

---

## Troubleshooting
- **Redirect loop to /login** – your session may have expired or been cleared. Log in again to mint fresh tokens.
- **401 or rate limiting errors** – Tesla may have revoked the token; log out and repeat the OAuth flow.
- **VIN modal renders off-screen** – ensure you are loading the bundled CSS (no CDN dependency) and check the browser console for blocking extensions.
- **Changes not visible** – restart the Poetry-run Uvicorn server after editing templates or Python modules.

---

## Contributing
Issues and pull requests are welcome. If you add new Tesla API calls, please avoid committing personal data and update this README so others understand the new behavior.

