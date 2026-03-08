from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
import threading
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobMetric:
    runs: int = 0
    failures: int = 0
    last_duration_ms: float | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_error_message: str | None = None
    last_details: dict[str, Any] = field(default_factory=dict)


class MetricsRegistry:
    def __init__(self, *, latency_samples: int = 2048, throughput_window_seconds: int = 60):
        self._lock = threading.Lock()
        self._latency_samples = max(128, latency_samples)
        self._throughput_window_seconds = max(10, throughput_window_seconds)

        self._http_total = 0
        self._http_errors = 0
        self._http_status_counts: dict[str, int] = defaultdict(int)
        self._http_path_counts: dict[str, int] = defaultdict(int)
        self._http_durations_ms: deque[float] = deque(maxlen=self._latency_samples)
        self._http_recent_timestamps: deque[float] = deque()

        self._jobs: dict[str, JobMetric] = defaultdict(JobMetric)

        self._action_status_counts: dict[str, int] = defaultdict(int)
        self._action_type_counts: dict[str, int] = defaultdict(int)
        self._idempotency_hits = 0

        self._alerts_sent = 0
        self._alerts_failed = 0
        self._alerts_by_channel: dict[str, int] = defaultdict(int)
        self._last_alert_at: str | None = None
        self._last_alert_error: str | None = None

    def record_http_request(self, *, method: str, path: str, status_code: int, duration_ms: float, now_ts: float) -> None:
        status_key = str(int(status_code))
        safe_method = (method or "GET").upper()
        safe_path = path or "/"
        bounded_duration = max(0.0, float(duration_ms))
        with self._lock:
            self._http_total += 1
            if status_code >= 500:
                self._http_errors += 1
            self._http_status_counts[status_key] += 1
            self._http_path_counts[f"{safe_method} {safe_path}"] += 1
            self._http_durations_ms.append(bounded_duration)
            self._http_recent_timestamps.append(float(now_ts))
            self._trim_recent_requests(now_ts=now_ts)

    def record_job_run(
        self,
        *,
        job_name: str,
        success: bool,
        duration_ms: float,
        details: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        key = (job_name or "unknown").strip().lower()
        now = _utc_now_iso()
        with self._lock:
            metric = self._jobs[key]
            metric.runs += 1
            metric.last_duration_ms = max(0.0, float(duration_ms))
            metric.last_details = dict(details or {})
            if success:
                metric.last_success_at = now
                metric.last_error_message = None
            else:
                metric.failures += 1
                metric.last_failure_at = now
                metric.last_error_message = (error_message or "").strip() or "unknown error"

    def record_action_result(self, *, action_type: str, status: str) -> None:
        safe_status = (status or "unknown").strip().lower()
        safe_type = (action_type or "unknown").strip().lower()
        with self._lock:
            self._action_status_counts[safe_status] += 1
            self._action_type_counts[f"{safe_type}:{safe_status}"] += 1

    def record_idempotency_hit(self, *, action_type: str) -> None:
        safe_type = (action_type or "unknown").strip().lower()
        with self._lock:
            self._idempotency_hits += 1
            self._action_type_counts[f"{safe_type}:idempotency_hit"] += 1

    def record_alert(self, *, delivered: bool, channel: str, error_message: str | None = None) -> None:
        safe_channel = (channel or "unknown").strip().lower()
        with self._lock:
            if delivered:
                self._alerts_sent += 1
                self._last_alert_at = _utc_now_iso()
                self._last_alert_error = None
                self._alerts_by_channel[safe_channel] += 1
            else:
                self._alerts_failed += 1
                self._last_alert_error = (error_message or "").strip() or "alert delivery failed"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now_ts = datetime.now(timezone.utc).timestamp()
            self._trim_recent_requests(now_ts=now_ts)
            latencies = list(self._http_durations_ms)
            p95 = _percentile(latencies, 95.0)
            avg = sum(latencies) / len(latencies) if latencies else 0.0
            throughput = len(self._http_recent_timestamps) / float(self._throughput_window_seconds)

            jobs = {
                name: {
                    "runs": metric.runs,
                    "failures": metric.failures,
                    "last_duration_ms": metric.last_duration_ms,
                    "last_success_at": metric.last_success_at,
                    "last_failure_at": metric.last_failure_at,
                    "last_error_message": metric.last_error_message,
                    "last_details": metric.last_details,
                }
                for name, metric in self._jobs.items()
            }

            top_paths = sorted(self._http_path_counts.items(), key=lambda item: item[1], reverse=True)[:15]
            http_paths = [{"path": name, "count": count} for name, count in top_paths]

            return {
                "generated_at": _utc_now_iso(),
                "http": {
                    "total_requests": self._http_total,
                    "error_requests": self._http_errors,
                    "error_rate": round((self._http_errors / self._http_total) if self._http_total else 0.0, 6),
                    "avg_latency_ms": round(avg, 2),
                    "p95_latency_ms": round(p95, 2),
                    "requests_per_second_last_minute": round(throughput, 3),
                    "status_counts": dict(self._http_status_counts),
                    "top_paths": http_paths,
                },
                "jobs": jobs,
                "actions": {
                    "status_counts": dict(self._action_status_counts),
                    "type_counts": dict(self._action_type_counts),
                    "idempotency_hits": self._idempotency_hits,
                },
                "alerts": {
                    "sent": self._alerts_sent,
                    "failed": self._alerts_failed,
                    "by_channel": dict(self._alerts_by_channel),
                    "last_sent_at": self._last_alert_at,
                    "last_error": self._last_alert_error,
                },
            }

    def _trim_recent_requests(self, *, now_ts: float) -> None:
        cutoff = now_ts - float(self._throughput_window_seconds)
        while self._http_recent_timestamps and self._http_recent_timestamps[0] < cutoff:
            self._http_recent_timestamps.popleft()


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    sorted_values = sorted(values)
    rank = max(0, min(len(sorted_values) - 1, int(round((p / 100.0) * (len(sorted_values) - 1)))))
    return float(sorted_values[rank])


@lru_cache
def get_metrics_registry() -> MetricsRegistry:
    return MetricsRegistry()
