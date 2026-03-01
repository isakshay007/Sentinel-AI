"""
SentinelAI — LogsMCP Server
Exposes log search and analysis tools via MCP protocol.

Tools:
  1. search_logs     — Search logs by query, severity, time range, service
  2. get_recent_errors — Get recent ERROR/WARN logs within a time window
  3. get_log_context  — Get surrounding log entries for a specific log

Run:
  python -m mcp_servers.logs_server

Test with MCP Inspector:
  mcp dev mcp_servers/logs_server.py
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Initialize the MCP server
mcp = FastMCP("SentinelAI-Logs")

# =============================================================================
# DATA LAYER — Loads mock data from fixtures
# =============================================================================

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"

def _load_all_logs() -> list[dict]:
    """Load all logs from all scenario fixture files."""
    all_logs = []
    for filepath in FIXTURES_DIR.glob("*.json"):
        if filepath.name.startswith("_"):
            continue
        try:
            with open(filepath) as f:
                data = json.load(f)
            logs = data.get("logs", [])
            # Tag each log with the scenario it came from
            for log in logs:
                log["scenario"] = filepath.stem
            all_logs.extend(logs)
        except (json.JSONDecodeError, KeyError):
            continue
    # Sort by timestamp
    all_logs.sort(key=lambda x: x.get("timestamp", ""))
    return all_logs


def _get_logs() -> list[dict]:
    """Cached log loader."""
    if not hasattr(_get_logs, "_cache"):
        _get_logs._cache = _load_all_logs()
    return _get_logs._cache


# =============================================================================
# MCP TOOLS
# =============================================================================

@mcp.tool()
def search_logs(
    query: str,
    severity: Optional[str] = None,
    service: Optional[str] = None,
    minutes_ago: int = 60,
    max_results: int = 20
) -> str:
    """
    Search application logs by keyword, severity, service, and time range.
    
    Use this tool to find specific log entries that match a search query.
    Results are returned in chronological order.
    
    Args:
        query: Search term to match against log messages (case-insensitive)
        severity: Filter by severity level: INFO, WARN, or ERROR
        service: Filter by service name (e.g., 'user-service', 'api-gateway')
        minutes_ago: How far back to search in minutes (default: 60)
        max_results: Maximum number of results to return (default: 20)
    
    Returns:
        JSON string with matching log entries and search metadata
    """
    logs = _get_logs()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)

    results = []
    for log in logs:
        # Time filter
        try:
            log_time = datetime.fromisoformat(log["timestamp"])
            if log_time.tzinfo is None:
                log_time = log_time.replace(tzinfo=timezone.utc)
            if log_time < cutoff:
                continue
        except (ValueError, KeyError):
            continue

        # Severity filter
        if severity and log.get("severity", "").upper() != severity.upper():
            continue

        # Service filter
        if service and service.lower() not in log.get("service", "").lower():
            continue

        # Query match (search in message)
        if query.lower() not in log.get("message", "").lower():
            continue

        results.append(log)

        if len(results) >= max_results:
            break

    return json.dumps({
        "tool": "search_logs",
        "query": query,
        "filters": {
            "severity": severity,
            "service": service,
            "minutes_ago": minutes_ago,
        },
        "total_matches": len(results),
        "results": results,
    }, indent=2)


@mcp.tool()
def get_recent_errors(
    minutes: int = 30,
    service: Optional[str] = None,
    include_warnings: bool = True,
    max_results: int = 50
) -> str:
    """
    Get recent ERROR (and optionally WARN) log entries.
    
    Use this tool to quickly assess the current error landscape across
    all services or a specific service. Useful for initial incident triage.
    
    Args:
        minutes: How many minutes back to look (default: 30)
        service: Optional service name filter
        include_warnings: Whether to include WARN-level entries (default: True)
        max_results: Maximum number of results (default: 50)
    
    Returns:
        JSON string with recent errors, grouped by service, with counts
    """
    logs = _get_logs()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    target_severities = {"ERROR"}
    if include_warnings:
        target_severities.add("WARN")

    results = []
    service_counts = {}

    for log in logs:
        # Time filter
        try:
            log_time = datetime.fromisoformat(log["timestamp"])
            if log_time.tzinfo is None:
                log_time = log_time.replace(tzinfo=timezone.utc)
            if log_time < cutoff:
                continue
        except (ValueError, KeyError):
            continue

        # Severity filter
        if log.get("severity", "").upper() not in target_severities:
            continue

        # Service filter
        if service and service.lower() not in log.get("service", "").lower():
            continue

        svc = log.get("service", "unknown")
        service_counts[svc] = service_counts.get(svc, {"ERROR": 0, "WARN": 0})
        service_counts[svc][log.get("severity", "ERROR")] += 1

        results.append(log)
        if len(results) >= max_results:
            break

    # Sort by severity (ERROR first), then by timestamp
    results.sort(key=lambda x: (0 if x.get("severity") == "ERROR" else 1, x.get("timestamp", "")))

    return json.dumps({
        "tool": "get_recent_errors",
        "time_window_minutes": minutes,
        "service_filter": service,
        "include_warnings": include_warnings,
        "summary": {
            "total_entries": len(results),
            "by_service": service_counts,
        },
        "results": results,
    }, indent=2)


@mcp.tool()
def get_log_context(
    log_id: str,
    before: int = 5,
    after: int = 5
) -> str:
    """
    Get surrounding log entries for a specific log entry.
    
    Use this tool when you've found an interesting log entry and want to
    see what happened immediately before and after it. This helps
    understand the sequence of events leading to an error.
    
    Args:
        log_id: The ID of the target log entry
        before: Number of log entries to include before the target (default: 5)
        after: Number of log entries to include after the target (default: 5)
    
    Returns:
        JSON string with the target log and its surrounding context
    """
    logs = _get_logs()

    # Find the target log by ID
    target_idx = None
    for i, log in enumerate(logs):
        if log.get("id") == log_id:
            target_idx = i
            break

    if target_idx is None:
        return json.dumps({
            "tool": "get_log_context",
            "error": f"Log entry with ID '{log_id}' not found",
            "suggestion": "Use search_logs or get_recent_errors to find valid log IDs first"
        }, indent=2)

    # Get surrounding entries
    start = max(0, target_idx - before)
    end = min(len(logs), target_idx + after + 1)

    context_logs = logs[start:end]

    # Mark which one is the target
    for i, log in enumerate(context_logs):
        log["is_target"] = (log.get("id") == log_id)

    return json.dumps({
        "tool": "get_log_context",
        "target_log_id": log_id,
        "target_index_in_context": target_idx - start,
        "context_range": {
            "before": target_idx - start,
            "after": end - target_idx - 1,
        },
        "target_service": logs[target_idx].get("service"),
        "results": context_logs,
    }, indent=2)


# =============================================================================
# MCP RESOURCES — Expose log summaries as readable resources
# =============================================================================

@mcp.resource("logs://summary")
def logs_summary() -> str:
    """Summary of all available log data."""
    logs = _get_logs()
    services = {}
    severities = {"INFO": 0, "WARN": 0, "ERROR": 0}

    for log in logs:
        svc = log.get("service", "unknown")
        sev = log.get("severity", "INFO")
        services[svc] = services.get(svc, 0) + 1
        if sev in severities:
            severities[sev] += 1

    return json.dumps({
        "total_logs": len(logs),
        "by_service": services,
        "by_severity": severities,
        "scenarios_loaded": list(set(log.get("scenario", "unknown") for log in logs)),
        "time_range": {
            "earliest": logs[0]["timestamp"] if logs else None,
            "latest": logs[-1]["timestamp"] if logs else None,
        },
    }, indent=2)


# =============================================================================
# RUN
# =============================================================================

if __name__ == "__main__":
    mcp.run()