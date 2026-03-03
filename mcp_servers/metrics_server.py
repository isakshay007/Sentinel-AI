"""
SentinelAI — MetricsMCP Server (LIVE)
Exposes live Prometheus-backed metrics tools via MCP protocol.

Tools:
  1. get_current_metrics  — Get latest metrics for a service (from Prometheus)
  2. get_metric_history   — Get time-series metric data (from Prometheus)
  3. detect_anomaly       — Check if a metric is anomalous vs thresholds
  4. get_recent_errors    — Get recent error logs (via Loki)

Run:
  python -m mcp_servers.metrics_server
"""

import asyncio
import json
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

from backend.prometheus_client import (
    get_service_health,
    get_metric_history as prom_get_metric_history,
    check_anomalies,
    query_loki,
    THRESHOLDS,
)

mcp = FastMCP("SentinelAI-Metrics")


def _run(coro):
    """Run an async coroutine from a sync MCP tool function.

    FastMCP dispatches sync tools from within its own event loop, so plain
    asyncio.run() raises 'cannot be called from a running event loop'.
    We fall back to running the coroutine in a separate thread.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=15)
    else:
        return asyncio.run(coro)


@mcp.tool()
def get_current_metrics(service: str) -> str:
    """
    Get the most recent metrics snapshot for a specific service from Prometheus.

    Returns:
        JSON with the latest metric values and service health status.
    """
    try:
        health = _run(get_service_health(service))
    except Exception as e:
        return json.dumps(
            {
                "tool": "get_current_metrics",
                "error": str(e),
                "service": service,
            },
            indent=2,
        )

    return json.dumps(
        {
            "tool": "get_current_metrics",
            "service": service,
            "health_status": health.get("status", "unknown"),
            "metrics": {
                "cpu_percent": health.get("cpu_percent"),
                "memory_percent": health.get("memory_percent"),
                "response_time_ms": health.get("response_time_ms"),
                "error_rate": health.get("error_rate"),
            },
        },
        indent=2,
    )


@mcp.tool()
def get_metric_history(service: str, metric: str, minutes: int = 60) -> str:
    """
    Get time-series data for a specific metric over a time window from Prometheus.

    Args:
        service: Service name (e.g., 'user-service')
        metric: Metric name — one of: cpu_percent, memory_percent,
                response_time_ms, error_rate
        minutes: How many minutes of history to return (default: 60)
    """
    try:
        history = _run(prom_get_metric_history(service, metric, minutes))
    except Exception as e:
        return json.dumps(
            {
                "tool": "get_metric_history",
                "error": str(e),
                "service": service,
                "metric": metric,
            },
            indent=2,
        )

    history.update({"tool": "get_metric_history", "service": service, "metric": metric})
    return json.dumps(history, indent=2)


@mcp.tool()
def detect_anomaly(service: str, metric: str) -> str:
    """
    Check if a specific metric is currently anomalous for a service.

    Uses threshold-based comparison against THRESHOLDS.
    """
    threshold = THRESHOLDS.get(metric)

    try:
        health = _run(get_service_health(service))
    except Exception as e:
        logger.error("[METRICS_MCP] detect_anomaly error fetching health: %s", e)
        return json.dumps({
            "tool": "detect_anomaly",
            "service": service,
            "metric": metric,
            "is_anomalous": False,
            "severity": "unknown",
            "evidence": {"current_value": None, "threshold": threshold},
            "message": f"Error: {e}",
        }, indent=2)

    if not health or health.get("status") == "unknown":
        return json.dumps({
            "tool": "detect_anomaly",
            "service": service,
            "metric": metric,
            "is_anomalous": False,
            "severity": "unknown",
            "evidence": {"current_value": None, "threshold": threshold},
            "message": f"Could not retrieve health data for {service}",
        }, indent=2)

    current_value = health.get(metric)
    if current_value is not None:
        current_value = float(current_value)

    anomalous = False
    severity = "normal"

    if threshold is not None and current_value is not None:
        if current_value >= threshold * 1.2:
            anomalous = True
            severity = "critical"
        elif current_value >= threshold:
            anomalous = True
            severity = "warning"

    evidence = {"current_value": current_value, "threshold": threshold}

    return json.dumps({
        "tool": "detect_anomaly",
        "service": service,
        "metric": metric,
        "is_anomalous": anomalous,
        "anomalous": anomalous,
        "severity": severity,
        "evidence": evidence,
    }, indent=2)


@mcp.tool()
def get_recent_errors(service: str, minutes: int = 10) -> str:
    """
    Get recent error logs for a service via Loki.

    Returns:
        {
          "tool": "get_recent_errors",
          "service": service,
          "minutes": minutes,
          "error_count": N,
          "logs": [...]
        }
    """
    try:
        logs = _run(query_loki("error", service, minutes))
    except Exception as e:
        return json.dumps(
            {
                "tool": "get_recent_errors",
                "error": str(e),
                "service": service,
            },
            indent=2,
        )

    return json.dumps(
        {
            "tool": "get_recent_errors",
            "service": service,
            "minutes": minutes,
            "error_count": len(logs),
            "logs": logs,
        },
        indent=2,
    )


if __name__ == "__main__":
    mcp.run()