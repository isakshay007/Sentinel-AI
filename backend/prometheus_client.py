import asyncio
import logging
import math
import os
import time
from datetime import datetime, timezone
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

import httpx
import docker

logger = logging.getLogger(__name__)

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
LOKI_URL = os.getenv("LOKI_URL", "http://loki:3100")

SERVICES = ["user-service", "payment-service", "api-gateway"]

THRESHOLDS = {
    "memory_percent": 85.0,
    "cpu_percent": 80.0,
    "error_rate": 0.10,  # 10%
    "response_time_ms": 500.0,  # 500ms
}


async def _async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10.0)


async def prom_query(query: str) -> Optional[float]:
    """Run an instant PromQL query and return a single float value or None."""
    try:
        async with await _async_client() as client:
            resp = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query})
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error("[PROM_QUERY] Failed query=%s error=%s", query, e)
        raise

    if data.get("status") != "success":
        return None

    result = data.get("data", {}).get("result", [])
    if not result:
        return None

    # Handle both scalar and vector results
    if data["data"].get("resultType") == "scalar":
        _, value = data["data"]["result"]
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    sample = result[0]
    values = sample.get("value") or sample.get("values")
    if not values:
        return None

    # Instant query → single [ts, value]
    if isinstance(values, list) and len(values) == 2 and isinstance(values[0], (int, float, str)):
        _, v = values
    else:
        # Range-style array, take latest
        _, v = values[-1]

    try:
        val = float(v)
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    except (TypeError, ValueError):
        return None


async def prom_range_query(
    query: str,
    minutes_back: int = 60,
    step: str = "15s",
) -> List[Tuple[float, float]]:
    """Run a range PromQL query and return list of (timestamp, value)."""
    end = time.time()
    start = end - minutes_back * 60

    async with await _async_client() as client:
        resp = await client.get(
            f"{PROMETHEUS_URL}/api/v1/query_range",
            params={
                "query": query,
                "start": start,
                "end": end,
                "step": step,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "success":
        return []

    result = data.get("data", {}).get("result", [])
    if not result:
        return []

    series = result[0].get("values", [])
    out: List[Tuple[float, float]] = []
    for ts, v in series:
        try:
            out.append((float(ts), float(v)))
        except (TypeError, ValueError):
            continue
    return out


async def get_service_health(service: str) -> Dict[str, Any]:
    """
    Query core metrics for a service and return a health snapshot.

    Shape matches the ServiceHealthResponse used by the dashboard.
    """
    # up metric (from Prometheus scrape)
    up_query = f'up{{job="{service}"}}'
    up = await prom_query(up_query)

    cpu_query = f'service_cpu_percent{{service="{service}"}}'
    mem_query = f'service_memory_percent{{service="{service}"}}'
    rt_query = (
        f'histogram_quantile(0.95, '
        f'sum by(le, service)(rate(http_request_duration_seconds_bucket{{service="{service}"}}[5m]))) * 1000'
    )
    err_query = (
        f'sum(rate(http_requests_total{{service="{service}",status=~"5.."}}[5m])) / '
        f'sum(rate(http_requests_total{{service="{service}"}}[5m]))'
    )

    cpu = await prom_query(cpu_query)
    mem = await prom_query(mem_query)
    rt = await prom_query(rt_query)
    if rt is None:
        rt_fallback = (
            f'rate(http_request_duration_seconds_sum{{service="{service}"}}[5m]) / '
            f'rate(http_request_duration_seconds_count{{service="{service}"}}[5m]) * 1000'
        )
        rt = await prom_query(rt_fallback)
    err = await prom_query(err_query)

    status = "unknown"
    if up is not None and up == 0:
        status = "critical"
    else:
        breaches = 0
        if mem is not None and mem >= THRESHOLDS["memory_percent"]:
            breaches += 1
        if cpu is not None and cpu >= THRESHOLDS["cpu_percent"]:
            breaches += 1
        if err is not None and err >= THRESHOLDS["error_rate"]:
            breaches += 1
        if rt is not None and rt >= THRESHOLDS["response_time_ms"]:
            breaches += 1

        if breaches == 0:
            status = "healthy"
        elif breaches == 1:
            status = "warning"
        else:
            status = "critical"

    health = {
        "service": service,
        "status": status,
        "cpu_percent": float(cpu) if cpu is not None else 0.0,
        "memory_percent": float(mem) if mem is not None else 0.0,
        "response_time_ms": float(rt) if rt is not None else 0.0,
        "error_rate": float(err) if err is not None else 0.0,
        "up": int(up) if up is not None else None,
    }
    return health


async def get_all_services_health() -> List[Dict[str, Any]]:
    """Return health snapshots for all monitored services."""
    results: List[Dict[str, Any]] = []
    for svc in SERVICES:
        results.append(await get_service_health(svc))
    return results


async def check_anomalies(service: str) -> Optional[Dict[str, Any]]:
    """
    Compare service metrics against thresholds.
    Returns None if healthy, otherwise anomaly description.
    """
    is_up = await prom_query(f'up{{job="{service}"}}')
    if is_up is None or is_up == 0:
        logger.warning("[ANOMALY_CHECK] service=%s is DOWN (up=0 or None)", service)
        return {
            "service": service,
            "anomalies": [
                {"metric": "up", "value": 0, "threshold": 1, "severity": "critical"},
            ],
            "worst_severity": "critical",
            "detection_metrics": {
                "status": "down",
                "up": 0,
                "cpu_percent": 0.0,
                "memory_percent": 0.0,
                "response_time_ms": 0.0,
                "error_rate": 0.0,
            },
        }

    health = await get_service_health(service)

    anomalies: List[Dict[str, Any]] = []

    def _classify(metric: str, value: float, threshold: float) -> Optional[str]:
        if value >= threshold * 1.2:
            return "critical"
        if value >= threshold:
            return "warning"
        return None

    for metric, threshold in THRESHOLDS.items():
        value = float(health.get(metric, 0.0))
        severity = _classify(metric, value, threshold)
        if metric == "response_time_ms" and severity == "warning":
            severity = "critical"
        if severity:
            anomalies.append(
                {
                    "metric": metric,
                    "value": value,
                    "threshold": threshold,
                    "severity": severity,
                }
            )

    up = health.get("up")
    if up == 0:
        anomalies.append(
            {
                "metric": "up",
                "value": 0,
                "threshold": 1,
                "severity": "critical",
            }
        )

    if not anomalies:
        return None

    worst_severity = "warning"
    if any(a["severity"] == "critical" for a in anomalies):
        worst_severity = "critical"

    return {
        "service": service,
        "anomalies": anomalies,
        "worst_severity": worst_severity,
        "detection_metrics": health,
    }


async def get_metric_history(service: str, metric: str, minutes: int = 60) -> Dict[str, Any]:
    """
    Return trend data for a metric:
    {
      data_points, trend, values, min, max, avg
    }
    """
    metric_map = {
        "cpu_percent": f'service_cpu_percent{{service="{service}"}}',
        "memory_percent": f'service_memory_percent{{service="{service}"}}',
        "response_time_ms": (
            f'histogram_quantile(0.95, '
            f'sum by(le, service)(rate(http_request_duration_seconds_bucket{{service="{service}"}}[5m]))) * 1000'
        ),
        "error_rate": (
            f'sum(rate(http_requests_total{{service="{service}",status=~"5.."}}[5m])) / '
            f'sum(rate(http_requests_total{{service="{service}"}}[5m]))'
        ),
    }
    promql = metric_map.get(metric)
    if not promql:
        return {
            "data_points": 0,
            "trend": "unknown",
            "values": [],
            "min": 0.0,
            "max": 0.0,
            "avg": 0.0,
        }

    series = await prom_range_query(promql, minutes_back=minutes)
    if not series:
        return {
            "data_points": 0,
            "trend": "unknown",
            "values": [],
            "min": 0.0,
            "max": 0.0,
            "avg": 0.0,
        }

    values = [v for _, v in series]
    n = len(values)
    min_v = min(values)
    max_v = max(values)
    avg_v = mean(values)

    # Trend based on first vs last 25%
    change_percent = 0.0
    latest_v = values[-1]
    if n >= 4:
        chunk = max(1, n // 4)
        first_avg = mean(values[:chunk])
        last_avg = mean(values[-chunk:])
        trend = "stable"
        if last_avg > first_avg * 1.2:
            trend = "increasing"
        elif last_avg < first_avg * 0.8:
            trend = "decreasing"
        else:
            # Simple oscillation heuristic
            if max_v - min_v > avg_v * 0.5:
                trend = "oscillating"
        if first_avg > 0:
            change_percent = (last_avg - first_avg) / first_avg * 100.0
    else:
        trend = "unknown"

    # Provide both a flat summary and a nested statistics block so existing
    # agents (Watcher) and docs expectations are satisfied.
    return {
        "data_points": n,
        "trend": trend,
        "values": series,
        "min": float(min_v),
        "max": float(max_v),
        "avg": float(avg_v),
        "statistics": {
            "trend": trend,
            "change_percent": float(change_percent),
            "min": float(min_v),
            "max": float(max_v),
            "latest": float(latest_v),
        },
    }


async def query_loki(query: str, service: str, minutes: int = 10) -> List[Dict[str, Any]]:
    """
    Query Loki for logs matching a string.
    Returns list of {timestamp, message, level}.
    """
    end = int(time.time() * 1e9)
    start = end - minutes * 60 * 1_000_000_000

    logql = f'{{container=~"sentinel-{service}.*"}} |= "{query}"'

    async with await _async_client() as client:
        resp = await client.get(
            f"{LOKI_URL}/loki/api/v1/query_range",
            params={
                "query": logql,
                "start": start,
                "end": end,
                "limit": 100,
                "direction": "BACKWARD",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    streams = data.get("data", {}).get("result", [])
    for stream in streams:
        values = stream.get("values", [])
        for ts, line in values:
            level = "INFO"
            msg = line
            # Try to parse JSON-structured logs
            try:
                import json as _json

                obj = _json.loads(line)
                msg = obj.get("message", line)
                level = obj.get("level", obj.get("severity", level))
            except Exception:
                pass

            try:
                ts_seconds = float(ts) / 1e9
            except (TypeError, ValueError):
                ts_seconds = time.time()

            ts_iso = datetime.fromtimestamp(ts_seconds, tz=timezone.utc).isoformat()
            results.append({"timestamp": ts_iso, "message": msg, "level": level})

    # Newest first already; keep as-is
    return results


_docker_client: Optional[docker.DockerClient] = None


def _get_docker_client() -> docker.DockerClient:
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


def get_deployment_history(service: str) -> Dict[str, Any]:
    """
    Return container info for a service.

    Note: In this single-version setup, restarts are NOT deployments.
    recent_deploy is always False; StartedAt only indicates container
    (re)start time, not a new code version.
    """
    client = _get_docker_client()
    container = client.containers.get(f"sentinel-{service}")
    image_tag = container.image.tags[0] if container.image.tags else "unknown"
    info = {
        "current_image": image_tag,
        "started_at": container.attrs["State"]["StartedAt"],
        "restart_count": container.attrs.get("RestartCount", 0),
        "status": container.status,
        "recent_deploy": False,
        "note": (
            "This infrastructure uses single-version containers. "
            "Restarts do not indicate code deployments."
        ),
    }
    return info


def get_deployment_info(service: str) -> Dict[str, Any]:
    """
    Backwards-compatible wrapper used by infra_server.

    For live SentinelAI we treat every container as single-version;
    only restarts change StartedAt, not the image version.
    """
    return get_deployment_history(service)


def _run_sync(coro):
    """Utility to run an async function from sync context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=15)
    return asyncio.run(coro)

