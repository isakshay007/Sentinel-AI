"""
SentinelAI — LogsMCP Server (LIVE)
Exposes log search and analysis tools via MCP protocol backed by Loki.

Tools:
  1. search_logs       — Search logs by query, severity, time range, service
  2. get_recent_errors — Get recent ERROR/WARN logs within a time window

Run:
  python -m mcp_servers.logs_server
"""

import asyncio
import json
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

from backend.prometheus_client import query_loki

# Initialize the MCP server
mcp = FastMCP("SentinelAI-Logs")


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
def search_logs(
    query: str,
    severity: Optional[str] = None,
    service: Optional[str] = None,
    minutes_ago: int = 60,
    max_results: int = 20,
) -> str:
    """
    Search application logs by keyword, severity, service, and time range via Loki.
    """
    if not service:
        # In this system logs are always scoped to a specific service
        return json.dumps(
            {
                "tool": "search_logs",
                "error": "service is required for live log search",
            },
            indent=2,
        )

    try:
        logs = _run(query_loki(query, service, minutes_ago))
    except Exception as e:
        return json.dumps(
            {
                "tool": "search_logs",
                "error": str(e),
                "service": service,
            },
            indent=2,
        )

    # Filter by severity if provided (case-insensitive)
    if severity:
        sev_upper = severity.upper()
        logs = [l for l in logs if l.get("level", "").upper() == sev_upper]

    results = logs[:max_results]

    return json.dumps(
        {
            "tool": "search_logs",
            "query": query,
            "filters": {
                "severity": severity,
                "service": service,
                "minutes_ago": minutes_ago,
            },
            "total_matches": len(results),
            "results": results,
        },
        indent=2,
    )


@mcp.tool()
def get_recent_errors(
    minutes: int = 30,
    service: Optional[str] = None,
    include_warnings: bool = True,
    max_results: int = 50,
) -> str:
    """
    Get recent ERROR (and optionally WARN) log entries from Loki.
    """
    if not service:
        return json.dumps(
            {
                "tool": "get_recent_errors",
                "error": "service is required for live log search",
            },
            indent=2,
        )

    try:
        logs = _run(query_loki("", service, minutes))
    except Exception as e:
        return json.dumps(
            {
                "tool": "get_recent_errors",
                "error": str(e),
                "service": service,
            },
            indent=2,
        )

    target_levels = {"ERROR"}
    if include_warnings:
        target_levels.add("WARN")
        target_levels.add("WARNING")

    filtered = [l for l in logs if l.get("level", "").upper() in target_levels]
    filtered = filtered[:max_results]

    return json.dumps(
        {
            "tool": "get_recent_errors",
            "time_window_minutes": minutes,
            "service_filter": service,
            "include_warnings": include_warnings,
            "summary": {
                "total_entries": len(filtered),
                "by_service": {service: {"ERROR": len(filtered)}},
            },
            "results": filtered,
        },
        indent=2,
    )


if __name__ == "__main__":
    mcp.run()