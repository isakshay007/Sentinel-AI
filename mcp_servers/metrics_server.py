"""
SentinelAI — MetricsMCP Server
Exposes system metrics tools via MCP protocol.

Tools:
  1. get_current_metrics  — Get latest metrics for a service
  2. get_metric_history   — Get time-series metric data
  3. detect_anomaly       — Check if a metric is anomalous

Run:
  python -m mcp_servers.metrics_server

Test with MCP Inspector:
  mcp dev mcp_servers/metrics_server.py
"""

import json
import statistics
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "SentinelAI-Metrics"
)

# =============================================================================
# DATA LAYER
# =============================================================================

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"

# Thresholds for anomaly detection (based on service baselines)
ANOMALY_THRESHOLDS = {
    "cpu_percent": {"warning": 75, "critical": 90},
    "memory_percent": {"warning": 80, "critical": 92},
    "response_time_ms": {"warning": 1000, "critical": 5000},
    "error_rate": {"warning": 0.05, "critical": 0.15},
    "gc_pause_ms": {"warning": 200, "critical": 500},
}


def _load_all_metrics() -> list[dict]:
    """Load all metrics from all scenario fixture files."""
    all_metrics = []
    for filepath in FIXTURES_DIR.glob("*.json"):
        if filepath.name.startswith("_"):
            continue
        try:
            with open(filepath) as f:
                data = json.load(f)
            metrics = data.get("metrics", [])
            for m in metrics:
                m["scenario"] = filepath.stem
            all_metrics.extend(metrics)
        except (json.JSONDecodeError, KeyError):
            continue
    all_metrics.sort(key=lambda x: x.get("timestamp", ""))
    return all_metrics


def _load_scenarios() -> dict[str, list[dict]]:
    """Load metrics grouped by scenario for targeted queries."""
    scenarios = {}
    for filepath in FIXTURES_DIR.glob("*.json"):
        if filepath.name.startswith("_"):
            continue
        try:
            with open(filepath) as f:
                data = json.load(f)
            metrics = data.get("metrics", [])
            for m in metrics:
                m["scenario"] = filepath.stem
            scenarios[filepath.stem] = sorted(metrics, key=lambda x: x.get("timestamp", ""))
        except (json.JSONDecodeError, KeyError):
            continue
    return scenarios


def _get_metrics() -> list[dict]:
    if not hasattr(_get_metrics, "_cache"):
        _get_metrics._cache = _load_all_metrics()
    return _get_metrics._cache


def _get_scenarios() -> dict[str, list[dict]]:
    if not hasattr(_get_scenarios, "_cache"):
        _get_scenarios._cache = _load_scenarios()
    return _get_scenarios._cache


def _filter_by_service(metrics: list[dict], service: str,
                       scenario: str = None) -> list[dict]:
    """Filter metrics by service, optionally within a specific scenario."""
    if scenario:
        scenario_metrics = _get_scenarios().get(scenario, [])
        return [m for m in scenario_metrics
                if service.lower() in m.get("service", "").lower()]
    return [m for m in metrics if service.lower() in m.get("service", "").lower()]


# =============================================================================
# MCP TOOLS
# =============================================================================

@mcp.tool()
def get_current_metrics(
    service: str,
    scenario: Optional[str] = None
) -> str:
    """
    Get the most recent metrics snapshot for a specific service.
    
    Returns the latest CPU, memory, response time, error rate, and
    other performance indicators for the specified service.
    
    Args:
        service: Service name (e.g., 'user-service', 'api-gateway',
                 'payment-service', 'inventory-service')
        scenario: Optional scenario filter (e.g., 'memory_leak', 'bad_deployment',
                  'api_timeout'). If specified, only returns metrics from that
                  scenario. If not specified, returns the worst-case metrics
                  across all scenarios for this service.
    
    Returns:
        JSON with the latest metric values and service health status
    """
    if scenario:
        metrics = _filter_by_service(_get_metrics(), service, scenario=scenario)
    else:
        # When no scenario specified, find the WORST current state
        # across all scenarios for this service (most useful for detection)
        all_scenarios = _get_scenarios()
        worst_metrics = None
        worst_severity = -1
        
        for sc_name, sc_metrics in all_scenarios.items():
            svc_metrics = [m for m in sc_metrics
                          if service.lower() in m.get("service", "").lower()]
            if not svc_metrics:
                continue
            latest = svc_metrics[-1]
            # Score severity by how many thresholds are breached
            severity_score = 0
            for metric_name, thresholds in ANOMALY_THRESHOLDS.items():
                val = latest.get(metric_name)
                if val is not None:
                    if val >= thresholds["critical"]:
                        severity_score += 2
                    elif val >= thresholds["warning"]:
                        severity_score += 1
            if severity_score > worst_severity:
                worst_severity = severity_score
                worst_metrics = svc_metrics
        
        metrics = worst_metrics if worst_metrics else _filter_by_service(_get_metrics(), service)

    if not metrics:
        return json.dumps({
            "tool": "get_current_metrics",
            "error": f"No metrics found for service '{service}'",
            "available_services": list(set(
                m.get("service") for m in _get_metrics()
            )),
        }, indent=2)

    latest = metrics[-1]

    # Determine health status based on thresholds
    health = "healthy"
    warnings = []
    for metric_name, thresholds in ANOMALY_THRESHOLDS.items():
        value = latest.get(metric_name)
        if value is None:
            continue
        if value >= thresholds["critical"]:
            health = "critical"
            warnings.append(f"{metric_name}={value} (critical threshold: {thresholds['critical']})")
        elif value >= thresholds["warning"]:
            if health != "critical":
                health = "warning"
            warnings.append(f"{metric_name}={value} (warning threshold: {thresholds['warning']})")

    return json.dumps({
        "tool": "get_current_metrics",
        "service": service,
        "timestamp": latest.get("timestamp"),
        "health_status": health,
        "warnings": warnings,
        "metrics": {
            "cpu_percent": latest.get("cpu_percent"),
            "memory_percent": latest.get("memory_percent"),
            "memory_used_mb": latest.get("memory_used_mb"),
            "memory_total_mb": latest.get("memory_total_mb", 2048),
            "response_time_ms": latest.get("response_time_ms"),
            "response_time_p99_ms": latest.get("response_time_p99_ms"),
            "error_rate": latest.get("error_rate"),
            "request_count": latest.get("request_count"),
            "active_connections": latest.get("active_connections"),
            "gc_pause_ms": latest.get("gc_pause_ms"),
        },
    }, indent=2)


@mcp.tool()
def get_metric_history(
    service: str,
    metric: str,
    minutes: int = 60,
    scenario: Optional[str] = None
) -> str:
    """
    Get time-series data for a specific metric over a time window.
    
    Use this to see how a metric has changed over time. Useful for
    identifying trends, spikes, and gradual degradation patterns.
    
    Args:
        service: Service name (e.g., 'user-service')
        metric: Metric name — one of: cpu_percent, memory_percent,
                response_time_ms, error_rate, gc_pause_ms, request_count
        minutes: How many minutes of history to return (default: 60)
        scenario: Optional scenario filter (e.g., 'memory_leak')
    
    Returns:
        JSON with time-series data points and basic statistics
    """
    valid_metrics = [
        "cpu_percent", "memory_percent", "response_time_ms",
        "error_rate", "gc_pause_ms", "request_count",
        "response_time_p99_ms", "active_connections", "memory_used_mb"
    ]

    if metric not in valid_metrics:
        return json.dumps({
            "tool": "get_metric_history",
            "error": f"Unknown metric '{metric}'",
            "valid_metrics": valid_metrics,
        }, indent=2)

    all_svc_metrics = _filter_by_service(_get_metrics(), service, scenario=scenario)
    if not all_svc_metrics:
        return json.dumps({
            "tool": "get_metric_history",
            "error": f"No metrics found for service '{service}'"
                     + (f" in scenario '{scenario}'" if scenario else ""),
        }, indent=2)

    # Filter by time
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    filtered = []
    for m in all_svc_metrics:
        try:
            ts = datetime.fromisoformat(m["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                filtered.append(m)
        except (ValueError, KeyError):
            continue

    # Extract the time series
    series = []
    values = []
    for m in filtered:
        val = m.get(metric)
        if val is not None:
            series.append({
                "timestamp": m["timestamp"],
                "value": val,
            })
            values.append(val)

    # Compute statistics
    stats = {}
    if values:
        stats = {
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "mean": round(statistics.mean(values), 4),
            "median": round(statistics.median(values), 4),
            "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else 0,
            "latest": round(values[-1], 4),
            "first": round(values[0], 4),
            "trend": "increasing" if values[-1] > values[0] * 1.2 else
                     "decreasing" if values[-1] < values[0] * 0.8 else "stable",
            "change_percent": round(
                ((values[-1] - values[0]) / values[0] * 100) if values[0] != 0 else 0, 2
            ),
        }

    return json.dumps({
        "tool": "get_metric_history",
        "service": service,
        "metric": metric,
        "time_window_minutes": minutes,
        "data_points": len(series),
        "statistics": stats,
        "series": series,
    }, indent=2)


@mcp.tool()
def detect_anomaly(
    service: str,
    metric: str,
    method: str = "threshold",
    scenario: Optional[str] = None
) -> str:
    """
    Check if a specific metric is currently anomalous for a service.
    
    Supports two detection methods:
      - 'threshold': Compare against predefined warning/critical thresholds
      - 'statistical': Compare latest value against historical mean ± 2 std devs
    
    Args:
        service: Service name
        metric: Metric name (cpu_percent, memory_percent, response_time_ms,
                error_rate, gc_pause_ms)
        method: Detection method — 'threshold' or 'statistical' (default: threshold)
        scenario: Optional scenario filter (e.g., 'memory_leak')
    
    Returns:
        JSON with anomaly detection result, including severity and evidence
    """
    all_svc_metrics = _filter_by_service(_get_metrics(), service, scenario=scenario)
    if not all_svc_metrics:
        return json.dumps({
            "tool": "detect_anomaly",
            "error": f"No metrics found for service '{service}'",
        }, indent=2)

    # Extract values for this metric
    values = [m.get(metric) for m in all_svc_metrics if m.get(metric) is not None]
    if not values:
        return json.dumps({
            "tool": "detect_anomaly",
            "error": f"No data for metric '{metric}' on service '{service}'",
        }, indent=2)

    latest = values[-1]
    is_anomalous = False
    severity = "normal"
    evidence = {}

    if method == "threshold":
        thresholds = ANOMALY_THRESHOLDS.get(metric)
        if not thresholds:
            return json.dumps({
                "tool": "detect_anomaly",
                "error": f"No thresholds defined for metric '{metric}'",
                "available_metrics": list(ANOMALY_THRESHOLDS.keys()),
            }, indent=2)

        if latest >= thresholds["critical"]:
            is_anomalous = True
            severity = "critical"
        elif latest >= thresholds["warning"]:
            is_anomalous = True
            severity = "warning"

        evidence = {
            "current_value": round(latest, 4),
            "warning_threshold": thresholds["warning"],
            "critical_threshold": thresholds["critical"],
            "method": "threshold",
        }

    elif method == "statistical":
        if len(values) < 10:
            return json.dumps({
                "tool": "detect_anomaly",
                "error": "Not enough data points for statistical analysis (need ≥ 10)",
                "data_points_available": len(values),
            }, indent=2)

        # Use the first third of data as baseline — this catches gradual
        # degradation that a full-history baseline would miss
        baseline_end = max(5, len(values) // 3)
        baseline = values[:baseline_end]
        mean = statistics.mean(baseline)
        stdev = statistics.stdev(baseline)
        z_score = (latest - mean) / stdev if stdev > 0 else 0

        if abs(z_score) > 3:
            is_anomalous = True
            severity = "critical"
        elif abs(z_score) > 2:
            is_anomalous = True
            severity = "warning"

        evidence = {
            "current_value": round(latest, 4),
            "baseline_mean": round(mean, 4),
            "baseline_stdev": round(stdev, 4),
            "z_score": round(z_score, 2),
            "method": "statistical",
            "baseline_period": f"first {baseline_end} of {len(values)} data points",
            "baseline_data_points": baseline_end,
        }

    else:
        return json.dumps({
            "tool": "detect_anomaly",
            "error": f"Unknown method '{method}'. Use 'threshold' or 'statistical'",
        }, indent=2)

    return json.dumps({
        "tool": "detect_anomaly",
        "service": service,
        "metric": metric,
        "is_anomalous": is_anomalous,
        "severity": severity,
        "evidence": evidence,
        "timestamp": all_svc_metrics[-1].get("timestamp"),
    }, indent=2)


# =============================================================================
# MCP RESOURCES
# =============================================================================

@mcp.resource("metrics://services")
def available_services() -> str:
    """List all services with available metrics."""
    metrics = _get_metrics()
    services = {}
    for m in metrics:
        svc = m.get("service", "unknown")
        if svc not in services:
            services[svc] = {"data_points": 0, "scenarios": set()}
        services[svc]["data_points"] += 1
        services[svc]["scenarios"].add(m.get("scenario", "unknown"))

    # Convert sets to lists for JSON serialization
    for svc in services:
        services[svc]["scenarios"] = list(services[svc]["scenarios"])

    return json.dumps(services, indent=2)


if __name__ == "__main__":
    mcp.run()