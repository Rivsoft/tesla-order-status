from __future__ import annotations

import os
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Dict


@dataclass
class Snapshot:
    total: int
    per_path: Dict[str, int]


class VisitMetrics:
    """In-memory counter that logs aggregated visit statistics."""

    def __init__(self, *, log_every: int = 25, log_interval: int = 300) -> None:
        self._total = 0
        self._per_path: Counter[str] = Counter()
        self._last_log = 0.0
        self._log_every = max(1, log_every)
        self._log_interval = max(10, log_interval)
        self._lock = threading.Lock()

    def record(self, path: str, *, logger) -> None:  # pragma: no cover - lock timing
        if not path:
            path = "<unknown>"
        timestamp = time.time()
        with self._lock:
            self._total += 1
            self._per_path[path] += 1
            should_log = self._should_log(timestamp)
            snapshot = self._snapshot_locked() if should_log else None
            if should_log:
                self._last_log = timestamp
        if snapshot:
            logger.info(
                "visit-metrics total=%s breakdown=%s",
                snapshot.total,
                self._format_breakdown(snapshot.per_path),
            )

    def force_log(self, *, logger) -> None:
        with self._lock:
            snapshot = self._snapshot_locked()
        logger.info(
            "visit-metrics total=%s breakdown=%s",
            snapshot.total,
            self._format_breakdown(snapshot.per_path),
        )

    def _should_log(self, timestamp: float) -> bool:
        if self._total % self._log_every == 0:
            return True
        if timestamp - self._last_log >= self._log_interval:
            return True
        return False

    def _snapshot_locked(self) -> Snapshot:
        return Snapshot(total=self._total, per_path=dict(self._per_path))

    @staticmethod
    def _format_breakdown(per_path: Dict[str, int]) -> str:
        if not per_path:
            return "<none>"
        ordered = sorted(per_path.items(), key=lambda item: item[0])
        return ", ".join(f"{route}:{count}" for route, count in ordered)


def build_metrics_from_env() -> VisitMetrics:
    log_every = int(os.getenv("METRIC_LOG_EVERY", "25"))
    log_interval = int(os.getenv("METRIC_LOG_INTERVAL", "300"))
    return VisitMetrics(log_every=log_every, log_interval=log_interval)
