## Tesla Order Status Dashboard

Modern FastAPI dashboard that visualizes the latest Tesla order data, VIN metadata, delivery blockers, and Tesla task progression. The UI persists Tesla API tokens locally so you can refresh data without re-authenticating every time.

### Highlights
- Responsive dashboard cards with VIN carousel, decoded VIN modal, and task timelines.
- Delivery, registration, finance, and metadata insights extracted from the Tesla Owner API.
- Manual refresh endpoint plus background caching in `tesla_orders.json`.
- Works locally with Poetry or in production via Docker Compose.

---

## Requirements
- Tesla account with an active order (needed for the OAuth device flow).
- Python 3.11+ (for local development) **or** Docker + Docker Compose.
- `tesla_tokens.json` and `tesla_orders.json` files in the project root (can be empty; they store the OAuth tokens and cached payload).

> ℹ️ When using Docker bind mounts you must create the two JSON files before starting the container so Docker can map them.

```
type nul > tesla_tokens.json
type nul > tesla_orders.json
```

---

## Running with Docker (Recommended)
```bash
docker-compose up --build
```
The dashboard is now available at [http://localhost:8000](http://localhost:8000). Containers mount `tesla_tokens.json` and `tesla_orders.json` so logins and cached responses survive restarts.

Stop everything with `docker-compose down`.

---

## Local Development with Poetry
1. Install Poetry if you do not have it yet:
   ```bash
   pip install poetry
   ```
2. Install dependencies and set up the virtual environment:
   ```bash
   poetry install
   ```
3. Start the FastAPI server:
   ```bash
   poetry run uvicorn app.main:app --reload
   ```
4. Visit [http://localhost:8000](http://localhost:8000).

---

## Authenticating with Tesla
1. Launch the app and navigate to `/login`.
2. Click **Open Tesla Login** to start the OAuth flow in a new browser tab.
3. After Tesla redirects you to `https://auth.tesla.com/void/callback?...`, copy that full URL (the page will show “Page Not Found,” which is expected).
4. Paste the URL into the form on `/login` and submit.

The callback stores access and refresh tokens in `tesla_tokens.json`. You can revoke access at any time via Tesla’s security settings; then delete the JSON file locally.

### Refreshing Order Data
- Use the **Refresh Orders** button on the dashboard or hit `GET /refresh`. Responses are cached in `tesla_orders.json` so the UI can render instantly on the next load.

---

## CLI & Utilities

| Tool | Command | Purpose |
| ---- | ------- | ------- |
| `tesla_order_status.py` | `python tesla_order_status.py` | Authenticates, downloads the latest Tesla order payload, prints a CLI summary, and writes `tesla_orders.json`. Useful for cron jobs or verifying API connectivity without the UI. |
| VIN decoder check | `poetry run python scripts/validate_vin_decoder.py` | Compares the built-in VIN decoder with NHTSA’s VPIC API for a curated set of VINs. Requires internet access. |

---

## Preview

#### Main Dashboard
![Image](https://github.com/user-attachments/assets/b19cf27c-e3a3-48a0-9b7f-ec2c649e4166)

#### Change Tracking View
![Image](https://github.com/user-attachments/assets/4f1f05cb-743e-4605-97ff-3c1d0d6ff67d)

---

## Project Structure
```
app/
  main.py            # FastAPI entrypoint & routes
  monitor.py         # Tesla API client + caching helpers
  vin_decoder.py     # Offline VIN metadata decoder
  templates/         # Jinja2 templates for dashboard + login flow
  static/            # CSS/JS assets
scripts/
  validate_vin_decoder.py
tesla_order_status.py # CLI helper to fetch & diff orders
docker-compose.yml    # Production-ready stack
```

---

## Troubleshooting
- **Missing tokens file**: if the app keeps redirecting to `/login`, ensure `tesla_tokens.json` exists and is writable by the process/container.
- **Docker file mounts become directories**: create blank `tesla_tokens.json` and `tesla_orders.json` before running `docker-compose up`.
- **Rate limiting or 401 responses**: re-authenticate via `/login`, or run `python tesla_order_status.py` to refresh tokens.

Feel free to open issues or PRs if you run into problems or want to add features.

