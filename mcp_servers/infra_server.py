"""
SentinelAI — InfraMCP Server
Exposes infrastructure action tools via MCP protocol.

These tools SIMULATE infrastructure actions (restart, scale, rollback).
In production, they would call real cloud APIs. Here they update state
and return realistic responses.

Safety: Each action is tagged with a risk level (safe/risky/dangerous).
Agents must check risk level before executing. Dangerous actions require
human approval (enforced in Week 5).

Tools:
  1. restart_service       — Restart a service instance
  2. scale_service         — Scale service replicas up/down
  3. rollback_deployment   — Roll back to a previous version
  4. get_deployment_history — Get recent deployment events

Run:
  python -m mcp_servers.infra_server
"""

import json
import uuid
import time
import random
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "SentinelAI-Infra")

# =============================================================================
# SIMULATED INFRASTRUCTURE STATE
# =============================================================================

# In-memory state tracking (simulates real infrastructure)
_infra_state = {
    "api-gateway": {
        "status": "running",
        "replicas": 2,
        "current_version": "v3.2.8",
        "previous_versions": ["v3.2.7", "v3.2.6", "v3.2.5"],
        "restart_count": 0,
        "last_restart": None,
        "uptime_seconds": 86400,
    },
    "user-service": {
        "status": "running",
        "replicas": 3,
        "current_version": "v2.15.4",
        "previous_versions": ["v2.15.3", "v2.15.2", "v2.15.1"],
        "restart_count": 0,
        "last_restart": None,
        "uptime_seconds": 172800,
    },
    "payment-service": {
        "status": "running",
        "replicas": 2,
        "current_version": "v3.8.13",
        "previous_versions": ["v3.8.12", "v3.8.11", "v3.8.10"],
        "restart_count": 0,
        "last_restart": None,
        "uptime_seconds": 43200,
    },
    "inventory-service": {
        "status": "running",
        "replicas": 2,
        "current_version": "v1.9.22",
        "previous_versions": ["v1.9.21", "v1.9.20", "v1.9.19"],
        "restart_count": 0,
        "last_restart": None,
        "uptime_seconds": 259200,
    },
}

# Action log — every action is recorded for audit
_action_log = []


def _log_action(action: str, service: str, details: dict, risk: str):
    """Record every infrastructure action for audit trail."""
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "service": service,
        "risk_level": risk,
        "details": details,
    }
    _action_log.append(entry)
    return entry


# =============================================================================
# DATA LAYER — Load deployment history from fixtures
# =============================================================================

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


def _load_deployment_history() -> list[dict]:
    """Load deployment events from fixture files."""
    deploys = []
    for filepath in FIXTURES_DIR.glob("*.json"):
        if filepath.name.startswith("_"):
            continue
        try:
            with open(filepath) as f:
                data = json.load(f)
            file_deploys = data.get("deployments", [])
            for d in file_deploys:
                d["scenario"] = filepath.stem
            deploys.extend(file_deploys)
        except (json.JSONDecodeError, KeyError):
            continue
    deploys.sort(key=lambda x: x.get("timestamp", ""))
    return deploys


# =============================================================================
# MCP TOOLS
# =============================================================================

@mcp.tool()
def restart_service(
    service: str,
    reason: str = "manual restart"
) -> str:
    """
    Restart a service instance. This performs a graceful restart:
    drains connections, stops the process, and starts a fresh instance.
    
    Risk level: RISKY — Service will be temporarily unavailable during restart.
    Expected downtime: 10-30 seconds.
    
    Args:
        service: Service name to restart (e.g., 'user-service')
        reason: Why the restart is being performed (for audit log)
    
    Returns:
        JSON with restart result, timing, and new service state
    """
    if service not in _infra_state:
        return json.dumps({
            "tool": "restart_service",
            "error": f"Unknown service '{service}'",
            "available_services": list(_infra_state.keys()),
        }, indent=2)

    state = _infra_state[service]

    # Simulate restart timing
    drain_time = round(random.uniform(2.0, 5.0), 1)
    stop_time = round(random.uniform(1.0, 3.0), 1)
    start_time = round(random.uniform(3.0, 8.0), 1)
    total_time = drain_time + stop_time + start_time

    # Update state
    state["restart_count"] += 1
    state["last_restart"] = datetime.now(timezone.utc).isoformat()
    state["uptime_seconds"] = 0
    state["status"] = "running"

    details = {
        "reason": reason,
        "drain_time_seconds": drain_time,
        "stop_time_seconds": stop_time,
        "start_time_seconds": start_time,
        "total_downtime_seconds": round(total_time, 1),
        "restart_number": state["restart_count"],
    }

    audit = _log_action("restart_service", service, details, risk="risky")

    return json.dumps({
        "tool": "restart_service",
        "risk_level": "risky",
        "status": "success",
        "service": service,
        "result": {
            "action": "restart",
            "total_downtime_seconds": round(total_time, 1),
            "phases": {
                "connection_drain": f"{drain_time}s",
                "process_stop": f"{stop_time}s",
                "process_start": f"{start_time}s",
            },
            "service_state": {
                "status": state["status"],
                "version": state["current_version"],
                "replicas": state["replicas"],
                "uptime_seconds": state["uptime_seconds"],
                "total_restarts": state["restart_count"],
            },
        },
        "audit_id": audit["id"],
    }, indent=2)


@mcp.tool()
def scale_service(
    service: str,
    replicas: int,
    reason: str = "auto-scale"
) -> str:
    """
    Scale a service to a specific number of replicas.
    
    Risk level:
      - SAFE if scaling up (adding capacity)
      - RISKY if scaling down (removing capacity under load)
    
    Args:
        service: Service name to scale
        replicas: Target number of replicas (1-10)
        reason: Why scaling is being performed (for audit log)
    
    Returns:
        JSON with scaling result, previous/new replica count
    """
    if service not in _infra_state:
        return json.dumps({
            "tool": "scale_service",
            "error": f"Unknown service '{service}'",
            "available_services": list(_infra_state.keys()),
        }, indent=2)

    if replicas < 1 or replicas > 10:
        return json.dumps({
            "tool": "scale_service",
            "error": f"Invalid replica count: {replicas}. Must be between 1 and 10.",
        }, indent=2)

    state = _infra_state[service]
    previous_replicas = state["replicas"]
    direction = "up" if replicas > previous_replicas else "down" if replicas < previous_replicas else "none"
    risk = "safe" if direction == "up" else "risky" if direction == "down" else "safe"

    # Simulate scaling time
    scale_time = abs(replicas - previous_replicas) * round(random.uniform(3.0, 8.0), 1)

    state["replicas"] = replicas

    details = {
        "previous_replicas": previous_replicas,
        "new_replicas": replicas,
        "direction": direction,
        "reason": reason,
        "scale_time_seconds": round(scale_time, 1),
    }

    audit = _log_action("scale_service", service, details, risk=risk)

    return json.dumps({
        "tool": "scale_service",
        "risk_level": risk,
        "status": "success",
        "service": service,
        "result": {
            "action": f"scale_{direction}",
            "previous_replicas": previous_replicas,
            "new_replicas": replicas,
            "scale_time_seconds": round(scale_time, 1),
            "service_state": {
                "status": state["status"],
                "version": state["current_version"],
                "replicas": state["replicas"],
            },
        },
        "audit_id": audit["id"],
    }, indent=2)


@mcp.tool()
def rollback_deployment(
    service: str,
    target_version: Optional[str] = None,
    reason: str = "incident rollback"
) -> str:
    """
    Roll back a service to a previous deployment version.
    
    Risk level: DANGEROUS — This changes running code in production.
    Should require human approval in production workflows.
    
    If no target_version is specified, rolls back to the immediately
    previous version.
    
    Args:
        service: Service name to rollback
        target_version: Specific version to roll back to (e.g., 'v3.8.12').
                       If not specified, uses the most recent previous version.
        reason: Why the rollback is being performed
    
    Returns:
        JSON with rollback result, version change details
    """
    if service not in _infra_state:
        return json.dumps({
            "tool": "rollback_deployment",
            "error": f"Unknown service '{service}'",
            "available_services": list(_infra_state.keys()),
        }, indent=2)

    state = _infra_state[service]
    current_version = state["current_version"]
    available_versions = state["previous_versions"]

    if not available_versions:
        return json.dumps({
            "tool": "rollback_deployment",
            "error": f"No previous versions available for '{service}'",
        }, indent=2)

    if target_version:
        if target_version not in available_versions:
            return json.dumps({
                "tool": "rollback_deployment",
                "error": f"Version '{target_version}' not found in rollback history",
                "available_versions": available_versions,
            }, indent=2)
        rollback_to = target_version
    else:
        rollback_to = available_versions[0]  # Most recent previous

    # Simulate rollback timing
    pull_time = round(random.uniform(5.0, 15.0), 1)
    deploy_time = round(random.uniform(10.0, 30.0), 1)
    health_check_time = round(random.uniform(5.0, 15.0), 1)
    total_time = pull_time + deploy_time + health_check_time

    # Update state
    state["previous_versions"].insert(0, current_version)
    state["current_version"] = rollback_to
    state["uptime_seconds"] = 0

    details = {
        "from_version": current_version,
        "to_version": rollback_to,
        "reason": reason,
        "total_time_seconds": round(total_time, 1),
    }

    audit = _log_action("rollback_deployment", service, details, risk="dangerous")

    return json.dumps({
        "tool": "rollback_deployment",
        "risk_level": "dangerous",
        "requires_approval": True,
        "status": "success",
        "service": service,
        "result": {
            "action": "rollback",
            "from_version": current_version,
            "to_version": rollback_to,
            "phases": {
                "image_pull": f"{pull_time}s",
                "rolling_deploy": f"{deploy_time}s",
                "health_check": f"{health_check_time}s",
            },
            "total_time_seconds": round(total_time, 1),
            "service_state": {
                "status": state["status"],
                "version": state["current_version"],
                "replicas": state["replicas"],
                "available_rollback_versions": state["previous_versions"][:3],
            },
        },
        "audit_id": audit["id"],
    }, indent=2)


@mcp.tool()
def get_deployment_history(
    service: Optional[str] = None,
    limit: int = 10
) -> str:
    """
    Get recent deployment events, optionally filtered by service.
    
    Use this to understand what changed recently — helpful for
    correlating incidents with recent deployments.
    
    Risk level: SAFE — Read-only operation.
    
    Args:
        service: Optional service name filter
        limit: Maximum number of events to return (default: 10)
    
    Returns:
        JSON with deployment events and current version info
    """
    deploys = _load_deployment_history()

    if service:
        deploys = [d for d in deploys if service.lower() in d.get("service", "").lower()]

    deploys = deploys[-limit:]  # Most recent

    # Include current state
    current_versions = {}
    for svc_name, state in _infra_state.items():
        if service and service.lower() not in svc_name.lower():
            continue
        current_versions[svc_name] = {
            "version": state["current_version"],
            "replicas": state["replicas"],
            "status": state["status"],
        }

    return json.dumps({
        "tool": "get_deployment_history",
        "risk_level": "safe",
        "service_filter": service,
        "total_events": len(deploys),
        "current_state": current_versions,
        "action_log": _action_log[-5:] if _action_log else [],
        "deployments": deploys,
    }, indent=2)


# =============================================================================
# MCP RESOURCES
# =============================================================================

@mcp.resource("infra://state")
def infrastructure_state() -> str:
    """Current state of all managed infrastructure."""
    return json.dumps(_infra_state, indent=2, default=str)


@mcp.resource("infra://audit-log")
def audit_log() -> str:
    """Complete audit log of all infrastructure actions taken."""
    return json.dumps(_action_log, indent=2)


if __name__ == "__main__":
    mcp.run()