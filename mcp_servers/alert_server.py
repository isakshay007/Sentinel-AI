"""
SentinelAI — AlertMCP Server
Exposes notification and incident ticket tools via MCP protocol.

These tools SIMULATE sending notifications (Slack, email, PagerDuty)
and creating incident tickets. All actions are logged for audit.

Tools:
  1. send_notification     — Send alert via Slack/email/PagerDuty
  2. create_incident_ticket — Create an incident tracking ticket
  3. get_on_call_engineer  — Get current on-call rotation info

Run:
  python -m mcp_servers.alert_server
"""

import json
import uuid
import random
from datetime import datetime, timezone
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "SentinelAI-Alerts"
)

# =============================================================================
# SIMULATED STATE
# =============================================================================

# Notification log — every notification recorded
_notification_log = []

# Incident tickets
_tickets = []

# On-call rotation (simulated)
_on_call_rotation = {
    "current": {
        "primary": {
            "name": "Alice Chen",
            "email": "alice.chen@company.com",
            "slack": "@alice.chen",
            "phone": "+1-555-0101",
            "team": "Platform Engineering",
            "shift_start": "2026-01-15T08:00:00Z",
            "shift_end": "2026-01-16T08:00:00Z",
        },
        "secondary": {
            "name": "Bob Kumar",
            "email": "bob.kumar@company.com",
            "slack": "@bob.kumar",
            "phone": "+1-555-0102",
            "team": "Platform Engineering",
            "shift_start": "2026-01-15T08:00:00Z",
            "shift_end": "2026-01-16T08:00:00Z",
        },
    },
    "escalation_chain": [
        {"level": 1, "target": "Primary on-call", "wait_minutes": 0},
        {"level": 2, "target": "Secondary on-call", "wait_minutes": 10},
        {"level": 3, "target": "Engineering Manager (Maria Santos)", "wait_minutes": 20},
        {"level": 4, "target": "VP of Engineering (James Park)", "wait_minutes": 30},
    ],
}


# =============================================================================
# MCP TOOLS
# =============================================================================

@mcp.tool()
def send_notification(
    channel: str,
    message: str,
    severity: str = "medium",
    service: Optional[str] = None,
    incident_id: Optional[str] = None
) -> str:
    """
    Send a notification to a specified channel about an incident or event.
    
    Simulates sending to Slack, email, or PagerDuty. In production,
    this would integrate with real notification APIs.
    
    Risk level: SAFE — Informational action only.
    
    Args:
        channel: Where to send — 'slack', 'email', 'pagerduty', or 'all'
        message: The notification message content
        severity: Alert severity — 'low', 'medium', 'high', 'critical'
        service: Related service name (optional, for context)
        incident_id: Related incident ID (optional, for linking)
    
    Returns:
        JSON with delivery confirmation and notification ID
    """
    valid_channels = ["slack", "email", "pagerduty", "all"]
    if channel not in valid_channels:
        return json.dumps({
            "tool": "send_notification",
            "error": f"Unknown channel '{channel}'",
            "valid_channels": valid_channels,
        }, indent=2)

    valid_severities = ["low", "medium", "high", "critical"]
    if severity not in valid_severities:
        return json.dumps({
            "tool": "send_notification",
            "error": f"Unknown severity '{severity}'",
            "valid_severities": valid_severities,
        }, indent=2)

    notification_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Determine recipients based on severity
    recipients = []
    if channel in ("slack", "all"):
        slack_channel = {
            "low": "#ops-low-priority",
            "medium": "#ops-alerts",
            "high": "#ops-incidents",
            "critical": "#ops-critical",
        }[severity]
        recipients.append({
            "type": "slack",
            "target": slack_channel,
            "status": "delivered",
            "delivered_at": now,
        })

    if channel in ("email", "all"):
        on_call = _on_call_rotation["current"]["primary"]
        recipients.append({
            "type": "email",
            "target": on_call["email"],
            "status": "delivered",
            "delivered_at": now,
        })

    if channel in ("pagerduty", "all") and severity in ("high", "critical"):
        on_call = _on_call_rotation["current"]["primary"]
        recipients.append({
            "type": "pagerduty",
            "target": on_call["phone"],
            "status": "triggered",
            "delivered_at": now,
            "escalation_policy": "auto-escalate after 10 minutes",
        })

    # Record notification
    notification = {
        "id": notification_id,
        "timestamp": now,
        "channel": channel,
        "severity": severity,
        "message": message,
        "service": service,
        "incident_id": incident_id,
        "recipients": recipients,
    }
    _notification_log.append(notification)
    # Cap list to prevent unbounded growth in long-running processes
    if len(_notification_log) > 500:
        _notification_log[:] = _notification_log[-500:]

    return json.dumps({
        "tool": "send_notification",
        "risk_level": "safe",
        "status": "success",
        "notification_id": notification_id,
        "delivered_to": len(recipients),
        "recipients": recipients,
        "message_preview": message[:100] + ("..." if len(message) > 100 else ""),
        "escalation_active": severity in ("high", "critical"),
    }, indent=2)


@mcp.tool()
def create_incident_ticket(
    title: str,
    description: str,
    priority: str = "P2",
    service: Optional[str] = None,
    assigned_to: Optional[str] = None,
    related_incident_id: Optional[str] = None
) -> str:
    """
    Create an incident tracking ticket.
    
    Simulates creating a ticket in an incident management system
    (like PagerDuty, Jira, or OpsGenie). Automatically assigns
    to on-call if no assignee specified.
    
    Risk level: SAFE — Creates a tracking record only.
    
    Args:
        title: Short title for the incident
        description: Detailed description including symptoms and impact
        priority: Priority level — 'P1' (critical), 'P2' (high), 'P3' (medium), 'P4' (low)
        service: Affected service name
        assigned_to: Person to assign (default: current on-call)
        related_incident_id: Link to existing incident ID if this is related
    
    Returns:
        JSON with ticket ID, assignment, and escalation details
    """
    valid_priorities = ["P1", "P2", "P3", "P4"]
    if priority not in valid_priorities:
        return json.dumps({
            "tool": "create_incident_ticket",
            "error": f"Invalid priority '{priority}'",
            "valid_priorities": valid_priorities,
        }, indent=2)

    ticket_id = f"INC-{random.randint(10000, 99999)}"
    now = datetime.now(timezone.utc).isoformat()

    # Auto-assign to on-call if not specified
    if not assigned_to:
        assigned_to = _on_call_rotation["current"]["primary"]["name"]

    # Determine SLA based on priority
    sla_minutes = {"P1": 15, "P2": 60, "P3": 240, "P4": 1440}[priority]

    ticket = {
        "id": ticket_id,
        "title": title,
        "description": description,
        "priority": priority,
        "status": "open",
        "service": service,
        "assigned_to": assigned_to,
        "created_at": now,
        "sla_response_minutes": sla_minutes,
        "related_incident_id": related_incident_id,
    }
    _tickets.append(ticket)
    # Cap list to prevent unbounded growth
    if len(_tickets) > 500:
        _tickets[:] = _tickets[-500:]

    return json.dumps({
        "tool": "create_incident_ticket",
        "risk_level": "safe",
        "status": "success",
        "ticket": {
            "id": ticket_id,
            "title": title,
            "priority": priority,
            "assigned_to": assigned_to,
            "sla_response_minutes": sla_minutes,
            "sla_deadline": now,  # Simplified
            "status": "open",
        },
        "notifications_sent": {
            "assignee_notified": True,
            "channel": f"#ops-{'critical' if priority == 'P1' else 'incidents'}",
            "escalation_active": priority in ("P1", "P2"),
        },
    }, indent=2)


@mcp.tool()
def get_on_call_engineer(
    team: Optional[str] = None
) -> str:
    """
    Get the current on-call engineer and escalation chain.
    
    Use this to find out who should be notified about an incident
    and what the escalation path looks like.
    
    Risk level: SAFE — Read-only lookup.
    
    Args:
        team: Optional team name filter (default: returns all on-call info)
    
    Returns:
        JSON with primary/secondary on-call info and escalation chain
    """
    return json.dumps({
        "tool": "get_on_call_engineer",
        "risk_level": "safe",
        "current_rotation": _on_call_rotation["current"],
        "escalation_chain": _on_call_rotation["escalation_chain"],
        "total_open_tickets": len([t for t in _tickets if t["status"] == "open"]),
        "recent_notifications": len(_notification_log),
    }, indent=2)


# =============================================================================
# MCP RESOURCES
# =============================================================================

@mcp.resource("alerts://notifications")
def notification_history() -> str:
    """All notifications sent in this session."""
    return json.dumps(_notification_log, indent=2)


@mcp.resource("alerts://tickets")
def ticket_list() -> str:
    """All incident tickets created in this session."""
    return json.dumps(_tickets, indent=2)


if __name__ == "__main__":
    mcp.run()