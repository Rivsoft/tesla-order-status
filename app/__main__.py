"""CLI entrypoint for running the Tesla Order Status app."""
from __future__ import annotations

import argparse
import os
from typing import Optional

import uvicorn

APP_IMPORT_PATH = "app.main:app"


def _env_bool(key: str, fallback: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return fallback
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, fallback: Optional[int] = None) -> Optional[int]:
    value = os.getenv(key)
    if value is None:
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def main() -> None:
    """Parse CLI arguments and launch Uvicorn."""

    default_host = os.getenv("APP_HOST", "127.0.0.1")
    default_port = _env_int("APP_PORT", 8000) or 8000
    default_reload = _env_bool("APP_RELOAD", False)
    default_workers = _env_int("APP_WORKERS")
    default_log_level = os.getenv("UVICORN_LOG_LEVEL", "info")

    parser = argparse.ArgumentParser(
        description=(
            "Run the Tesla Order Status FastAPI application with sensible defaults "
            "(think `npm start`, but for this service)."
        )
    )
    parser.add_argument(
        "--host",
        default=default_host,
        help=f"Host interface to bind (default: {default_host!r}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=default_port,
        help=f"Port to bind (default: {default_port}).",
    )
    parser.add_argument(
        "--log-level",
        default=default_log_level,
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help=f"Uvicorn log level (default: {default_log_level}).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=default_workers,
        help=(
            "Number of worker processes (ignored when --reload is enabled). "
            + ("Default: APP_WORKERS env." if default_workers is not None else "Default: 1.")
        ),
    )
    parser.add_argument(
        "--reload",
        dest="reload",
        action="store_true",
        help="Enable auto-reload on code changes (defaults to APP_RELOAD env).",
    )
    parser.add_argument(
        "--no-reload",
        dest="reload",
        action="store_false",
        help="Disable auto-reload even if APP_RELOAD=1.",
    )
    parser.set_defaults(reload=default_reload)

    args = parser.parse_args()

    uvicorn.run(
        APP_IMPORT_PATH,
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
