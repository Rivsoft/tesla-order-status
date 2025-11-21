# Tesla Order Status Dashboard — Technical Guide

This document is for developers and self-hosters who want to understand how the project works under the hood or run their own instance. For the customer-facing experience, visit [tesla-tracker.rivsoft.org](https://tesla-tracker.rivsoft.org/) or read the top-level `README.md`.

---

## Architecture Overview
- **FastAPI app (`app/main.py`)** renders the dashboard via Jinja2 templates and exposes `/`, `/login`, `/refresh`, and `/history` routes.
- **Monitor service (`app/monitor.py`)** manages the Tesla Owner API session, refreshes OAuth tokens, and reshapes the data into UI-friendly dictionaries.
- **VIN decoder (`app/vin_decoder.py`)** offers offline decoding for the assigned VIN, with optional VPIC validation via `scripts/validate_vin_decoder.py`.
- **Service worker (`app/static/sw.js`)** injects client-held token bundles into every fetch, creating a lightweight privacy-preserving proxy.
- **Templates and static assets (`app/templates`, `app/static/js`)** power the dashboard UI, snapshot history drawer, and login flow.

All sensitive Tesla tokens remain in the browser (IndexedDB + service worker headers). The backend only receives the token bundle as part of the request, uses it immediately, and discards it.

---

## Requirements
- Tesla account with an active order capable of completing the OAuth redirect flow.
- **Python 3.11+** with [Poetry](https://python-poetry.org/) if you plan to run the app natively.
- Optional: Docker / Docker Compose if you prefer containerized deployments.

---

## Local Development with Poetry
1. Install Poetry:
   ```bash
   pip install poetry
   ```
2. Install dependencies:
   ```bash
   poetry install
   ```
3. Run the app with autoreload:
   ```bash
   poetry run uvicorn app.main:app --reload
   ```
4. Open `http://localhost:8000` in your browser.

Use `--port` to change the exposed port. Set environment variables before the command (e.g., `ENABLE_VISIT_METRICS=0 poetry run ...`).

---

## Docker Workflow
```bash
# Build
docker build -t tesla-order-status .

# Run (change the first port to remap locally)
docker run --rm -p 8000:8000 tesla-order-status
```

### Docker Compose
```bash
docker compose up --build
```
Compose maps port `8000:8000` by default. Stop with `Ctrl+C` or `docker compose down`.

---

## Configuration & Environment Variables
| Variable | Default | Description |
| -------- | ------- | ----------- |
| `ENABLE_VISIT_METRICS` | `1` | Enable the in-memory visit counter middleware. Set to `0` to disable. |
| `METRIC_LOG_EVERY` | `25` | Log after _N_ visits even if the time interval audit has not fired. |
| `METRIC_LOG_INTERVAL` | `300` | Minimum seconds between metric logs to avoid silence during low traffic. |

Add your own environment file or export values before starting the server.

---

## Authentication Flow Details
1. User opens `/login` and launches Tesla's official authentication portal via the **Open Tesla Login** button.
   - The server generates a PKCE `code_verifier` and stores it in a secure, HTTP-only cookie.
2. After successful sign-in, Tesla redirects to `https://auth.tesla.com/void/callback?...` with the authorization code in the query string.
3. The user copies the complete callback URL and submits it back to `/login`.
4. The backend retrieves the `code_verifier` from the cookie to exchange the code for access + refresh tokens.
5. Tokens are returned to the browser, and the service worker injects the token bundle as a custom header for all dashboard requests and persists updates in IndexedDB.

Tokens never persist on the server. Logout clears the browser storage and unregisters the service worker. Revoking the token inside Tesla's account settings also forces a fresh login.

---

## Snapshot History & Refresh Behavior
- **Client-Side Caching**: The Service Worker caches the dashboard HTML. Visiting `/` serves the cached version instantly without hitting the Tesla API.
- **Explicit Refresh**: Clicking "Refresh" navigates to `/?refreshed=1`, forcing the Service Worker to bypass the cache, fetch fresh data from the server (triggering a Tesla API call), and update the cache.
- **History**: Each successful fetch stores the raw payload in `localStorage` along with a timestamp. The `/history` page builds cards from those snapshots, highlighting differences field-by-field.

---

## Utilities
| Tool | Command | Purpose |
| ---- | ------- | ------- |
| VIN decoder regression | `poetry run python scripts/validate_vin_decoder.py` | Validates the bundled decoder against NHTSA's VPIC API (internet required). |
| Super Linter parity | `poetry run python scripts/run_super_linter.py` | Runs the same GitHub Super Linter configuration locally using Docker. |

---

## Project Layout
```text
app/
  main.py            # FastAPI entrypoint & routes
  monitor.py         # Tesla API client + normalization
  tesla_stores.py    # Delivery center helper data
  vin_decoder.py     # Offline VIN decoder
  templates/         # Jinja2 templates (index, login, history, etc.)
  static/
    sw.js            # Service worker injecting token headers
    js/
      app-init.js
      sw-register.js
      token-storage.js
scripts/
  validate_vin_decoder.py
  run_super_linter.py
README.md            # Customer-facing guide
docs/
  TECHNICAL_GUIDE.md # This file
```

---

## Troubleshooting
- **Redirect loop back to /login**: The client token bundle may be missing or expired. Re-run the Tesla OAuth flow.
- **401 responses or rate limits**: Tesla likely revoked the token; log out and authenticate again.
- **VIN modal renders incorrectly**: Ensure bundled CSS is loading and that no browser extension is blocking scripts.
- **Template changes not appearing**: Restart Uvicorn (or rebuild the Docker image) after editing templates or static files.

---

## Contribution Notes
- Keep new features privacy-friendly—avoid storing tokens or personal data on the server.
- Update both `README.md` and this document when you add user-visible behavior or developer dependencies.
- Validate your changes with the existing linting workflow (Super Linter or `poetry run` equivalents) before opening a PR.

For discussions, file an issue or pull request at [github.com/Rivsoft/tesla-order-status](https://github.com/Rivsoft/tesla-order-status).
