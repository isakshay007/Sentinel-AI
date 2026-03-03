"""
SentinelAI — Executor (Direct MCP Calls)
Executes remediation actions via MCP tool servers.
No LLM needed — the executor is a simple dispatcher.

Receives delegated tasks from the Strategist via A2A protocol and executes
them by calling the appropriate MCP server (InfraMCP for restart/scale,
AlertMCP for notifications/tickets).
"""

import asyncio
import concurrent.futures
import json
import logging
import sys
from datetime import datetime, timezone

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

# ─── Tool → MCP server mapping ───────────────────────────────────────────────

_TOOL_SERVER_MAP = {
    "restart_service": "mcp_servers.infra_server",
    "scale_service": "mcp_servers.infra_server",
    "flush_cache": "mcp_servers.infra_server",
    "get_container_status": "mcp_servers.infra_server",
    "get_deployment_history": "mcp_servers.infra_server",
    "send_notification": "mcp_servers.alert_server",
    "create_incident_ticket": "mcp_servers.alert_server",
}


# ─── MCP call helper ─────────────────────────────────────────────────────────

def _call_mcp_sync(server_module: str, tool_name: str, args: dict) -> dict:
    """Call an MCP tool synchronously by spawning the server as a subprocess."""

    async def _call():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", server_module],
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, args)
                    return json.loads(result.content[0].text)
        except Exception as e:
            return {"error": str(e), "tool": tool_name}

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _call()).result(timeout=30)
    else:
        return asyncio.run(_call())


# ─── Single-tool executor (called by approve_action) ─────────────────────────

def execute_single_tool(tool: str, tool_args: dict) -> dict:
    """
    Execute a single MCP tool.  Used when a human approves a pending action.
    Returns dict with ``status`` ('completed' | 'failed') and ``result`` / ``error``.
    """
    logger.info("[EXECUTOR] Executing tool=%s args=%s", tool, tool_args)
    server = _TOOL_SERVER_MAP.get(tool)
    if not server:
        logger.warning("[EXECUTOR] Unknown tool: %s", tool)
        return {"error": f"Unknown tool: {tool}", "status": "failed"}
    try:
        result = _call_mcp_sync(server, tool, tool_args)

        # Post-step: if we just restarted Redis, also flush cache
        if tool == "restart_service" and tool_args.get("service") == "redis":
            logger.info("[EXECUTOR] Redis restart detected — running flush_cache post-step")
            try:
                cache_result = _call_mcp_sync("mcp_servers.infra_server", "flush_cache", {})
                logger.debug("[EXECUTOR] flush_cache result=%s", cache_result)
                result = {"primary": result, "post_flush_cache": cache_result}
            except Exception as flush_err:
                result = {
                    "primary": result,
                    "post_flush_cache": {"status": "failed", "error": str(flush_err)},
                }

        logger.info("[EXECUTOR] Tool=%s completed success=%s", tool, "completed")
        return {"status": "completed", "result": result}
    except Exception as e:
        logger.error("[EXECUTOR] Tool=%s completed success=%s error=%s", tool, "failed", e)
        return {"error": str(e), "status": "failed"}


# ─── Multi-action executor (for full-pipeline CLI / testing) ─────────────────

def execute_actions(
    service: str,
    actions: list,
    incident_type: str = "unknown",
    root_cause: str = "Unknown",
    severity: str = "high",
) -> dict:
    """
    Execute a list of actions sequentially via direct MCP calls.
    Each action dict should have ``tool`` and ``tool_args`` keys.

    Returns a summary dict compatible with the old ``build_executor_crew`` shape.
    """
    results = []
    for action in actions:
        tool = action.get("tool", "")
        tool_args = action.get("tool_args", {})
        out = execute_single_tool(tool, tool_args)
        results.append({"tool": tool, **out})

    return {
        "status": "completed",
        "incident_type": incident_type,
        "service": service,
        "tasks_executed": len(actions),
        "results": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Full pipeline (Watcher → Diagnostician → Strategist → Executor) ─────────

async def full_pipeline_with_execution(service: str, scenario: str = None) -> dict:
    """Run the complete incident response pipeline including execution."""
    from agents.strategist import full_pipeline

    print(f"\n  Phases 1-3: Watcher → Diagnostician → Strategist...")
    pipeline_result = await full_pipeline(service, scenario)

    watcher = pipeline_result.get("watcher", {})
    diag = pipeline_result.get("diagnostician")
    strat = pipeline_result.get("strategist")

    if not strat:
        print("  No strategy produced. Stopping.")
        return pipeline_result

    diagnosis = diag.get("diagnosis", {}) if diag else {}
    incident_type = diagnosis.get("root_cause_category", scenario or "unknown")
    root_cause = diag.get("root_cause", "Unknown") if diag else "Unknown"
    severity = watcher.get("severity", "high")

    # Collect all approved (safe, auto-executed) actions
    approved = strat.get("approved_actions", [])
    # Pending (risky) actions would normally wait for human approval via the UI.
    # In CLI mode we execute them directly for testing.
    pending = strat.get("pending_actions", [])
    all_actions = approved + pending

    print(f"\n  Phase 4: Executing {len(all_actions)} actions via MCP...")
    print(f"  Incident type: {incident_type}")
    print(f"  Root cause: {root_cause[:80]}")

    exec_result = execute_actions(
        service=service,
        actions=all_actions,
        incident_type=incident_type,
        root_cause=root_cause,
        severity=severity,
    )

    return {
        "watcher": watcher,
        "diagnostician": diag,
        "strategist": strat,
        "executor": exec_result,
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SentinelAI Executor")
    parser.add_argument("--service", default="user-service")
    parser.add_argument("--scenario", default="memory_leak")
    parser.add_argument(
        "--full-pipeline",
        action="store_true",
        help="Run complete Watcher → Diagnostician → Strategist → Executor",
    )
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  SentinelAI Executor (Direct MCP)")
    print(f"  Service: {args.service}")
    print(f"  Scenario: {args.scenario}")
    print(f"{'='*60}")

    if args.full_pipeline:
        result = asyncio.run(full_pipeline_with_execution(args.service, args.scenario))
        exec_result = result.get("executor", {})
    else:
        print(f"\n  Running executor standalone for: {args.scenario}")
        exec_result = execute_actions(
            service=args.service,
            actions=[
                {
                    "tool": "send_notification",
                    "tool_args": {
                        "channel": "all",
                        "message": f"Test: {args.scenario} on {args.service}",
                        "severity": "critical",
                        "service": args.service,
                    },
                },
                {
                    "tool": "restart_service",
                    "tool_args": {
                        "service": args.service,
                        "reason": f"Test: remediate {args.scenario}",
                    },
                },
            ],
            incident_type=args.scenario,
            root_cause=f"Test: simulated {args.scenario} on {args.service}",
            severity="critical",
        )

    print(f"\n{'─'*60}")
    print(f"  EXECUTION RESULT")
    print(f"{'─'*60}")
    print(f"  Status:         {exec_result.get('status', 'N/A')}")
    print(f"  Tasks Executed: {exec_result.get('tasks_executed', 0)}")
    for r in exec_result.get("results", []):
        print(f"    - {r.get('tool', '?')}: {r.get('status', '?')}")
    print()
