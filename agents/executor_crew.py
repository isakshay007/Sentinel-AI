"""
SentinelAI — Executor Crew (CrewAI)
4 specialist agents that execute remediation actions via MCP tools.
Receives delegated tasks from the Strategist via A2A protocol.

Agents:
  1. ScaleAgent      — Scales services up/down via InfraMCP
  2. RestartAgent     — Restarts services via InfraMCP
  3. RollbackAgent    — Rolls back deployments via InfraMCP
  4. NotifyAgent      — Sends notifications via AlertMCP
"""

import json
import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import BaseTool
from pydantic import Field
from dotenv import load_dotenv

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from a2a.protocol import A2AClient, A2AServer, AGENT_CARDS, TaskStatus

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")


# =============================================================================
# LLM SETUP
# =============================================================================

groq_llm = LLM(
    model="groq/llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.1,
)


# =============================================================================
# MCP TOOL WRAPPERS — CrewAI-compatible tools that call MCP servers
# =============================================================================

def _call_mcp_sync(server_module: str, tool_name: str, args: dict) -> dict:
    """Synchronous wrapper around async MCP call for CrewAI compatibility."""
    async def _call():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", server_module]
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
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _call()).result()
        else:
            return asyncio.run(_call())
    except RuntimeError:
        return asyncio.run(_call())


class ScaleServiceTool(BaseTool):
    name: str = "scale_service"
    description: str = "Scale a service to a specific number of replicas. Args: service (str), replicas (int), reason (str)"

    def _run(self, service: str, replicas: int = 5, reason: str = "auto-scale") -> str:
        result = _call_mcp_sync(
            "mcp_servers.infra_server", "scale_service",
            {"service": service, "replicas": replicas, "reason": reason}
        )
        return json.dumps(result, indent=2)


class RestartServiceTool(BaseTool):
    name: str = "restart_service"
    description: str = "Restart a service with graceful connection draining. Args: service (str), reason (str)"

    def _run(self, service: str, reason: str = "incident remediation") -> str:
        result = _call_mcp_sync(
            "mcp_servers.infra_server", "restart_service",
            {"service": service, "reason": reason}
        )
        return json.dumps(result, indent=2)


class RollbackDeploymentTool(BaseTool):
    name: str = "rollback_deployment"
    description: str = "Roll back a service to its previous deployment version. Args: service (str), reason (str)"

    def _run(self, service: str, reason: str = "incident rollback") -> str:
        result = _call_mcp_sync(
            "mcp_servers.infra_server", "rollback_deployment",
            {"service": service, "reason": reason}
        )
        return json.dumps(result, indent=2)


class SendNotificationTool(BaseTool):
    name: str = "send_notification"
    description: str = "Send an alert notification. Args: channel (str: slack/email/pagerduty/all), message (str), severity (str: low/medium/high/critical), service (str: affected service name)"

    def _run(self, channel: str, message: str, severity: str, service: str) -> str:
        result = _call_mcp_sync(
            "mcp_servers.alert_server", "send_notification",
            {"channel": channel, "message": message, "severity": severity, "service": service}
        )
        return json.dumps(result, indent=2)


class CreateTicketTool(BaseTool):
    name: str = "create_incident_ticket"
    description: str = "Create an incident tracking ticket. Args: title (str), description (str), priority (str: P1/P2/P3/P4), service (str: affected service name)"

    def _run(self, title: str, description: str, priority: str, service: str) -> str:
        result = _call_mcp_sync(
            "mcp_servers.alert_server", "create_incident_ticket",
            {"title": title, "description": description, "priority": priority, "service": service}
        )
        return json.dumps(result, indent=2)


class GetDeployHistoryTool(BaseTool):
    name: str = "get_deployment_history"
    description: str = "Get recent deployment history for a service. Args: service (str)"

    def _run(self, service: str, limit: int = 5) -> str:
        result = _call_mcp_sync(
            "mcp_servers.infra_server", "get_deployment_history",
            {"service": service, "limit": limit}
        )
        return json.dumps(result, indent=2)


# =============================================================================
# CREWAI AGENTS
# =============================================================================

scale_agent = Agent(
    role="Infrastructure Scaler",
    goal="Scale services to the specified replica count. Use ONLY the scale_service tool. After calling the tool and getting a result, immediately report the result.",
    backstory=(
        "You are an infrastructure scaling specialist. You call scale_service "
        "with the provided parameters and report the result. Do not search the web. "
        "Do not use any tools other than scale_service."
    ),
    tools=[ScaleServiceTool()],
    llm=groq_llm,
    verbose=True,
    allow_delegation=False,
    max_iter=3,
)

restart_agent = Agent(
    role="Service Recovery Specialist",
    goal="Restart the specified service. Use ONLY the restart_service tool. After calling the tool and getting a result, immediately report the result.",
    backstory=(
        "You specialize in graceful service restarts. You call restart_service "
        "with the provided parameters and report the result. Do not search the web. "
        "Do not use any tools other than restart_service."
    ),
    tools=[RestartServiceTool()],
    llm=groq_llm,
    verbose=True,
    allow_delegation=False,
    max_iter=3,
)

rollback_agent = Agent(
    role="Deployment Rollback Engineer",
    goal="Roll back the specified service to a previous version. Use ONLY rollback_deployment and get_deployment_history tools. Report the result immediately after execution.",
    backstory=(
        "You handle emergency rollbacks. You may check deployment history first, "
        "then execute the rollback. Do not search the web. "
        "Do not use any tools other than rollback_deployment and get_deployment_history."
    ),
    tools=[RollbackDeploymentTool(), GetDeployHistoryTool()],
    llm=groq_llm,
    verbose=True,
    allow_delegation=False,
    max_iter=3,
)

notify_agent = Agent(
    role="Communications Officer",
    goal="Send notifications and create incident tickets. Use ONLY send_notification and create_incident_ticket tools. Report the result immediately after execution.",
    backstory=(
        "You handle incident communications. You send notifications and create "
        "tickets with the provided details. Do not search the web. "
        "Do not use any tools other than send_notification and create_incident_ticket."
    ),
    tools=[SendNotificationTool(), CreateTicketTool()],
    llm=groq_llm,
    verbose=True,
    allow_delegation=False,
    max_iter=3,
)


# =============================================================================
# SINGLE ACTION EXECUTION — For human-approved actions
# =============================================================================

_TOOL_SERVER_MAP = {
    "send_notification": "mcp_servers.alert_server",
    "create_incident_ticket": "mcp_servers.alert_server",
    "scale_service": "mcp_servers.infra_server",
    "restart_service": "mcp_servers.infra_server",
    "rollback_deployment": "mcp_servers.infra_server",
    "get_deployment_history": "mcp_servers.infra_server",
}


def execute_single_tool(tool: str, tool_args: dict) -> dict:
    """
    Execute a single MCP tool. Used when human approves a pending action.
    Returns dict with status, result/error.
    """
    server = _TOOL_SERVER_MAP.get(tool)
    if not server:
        return {"error": f"Unknown tool: {tool}", "status": "failed"}
    try:
        result = _call_mcp_sync(server, tool, tool_args)
        return {"status": "completed", "result": result}
    except Exception as e:
        return {"error": str(e), "status": "failed"}


# =============================================================================
# CREW BUILDER — Creates appropriate crew for an incident
# =============================================================================

def build_executor_crew(
    incident_type: str,
    service: str,
    root_cause: str,
    severity: str = "high",
    actions: list = None,
) -> dict:
    """
    Build and run a CrewAI crew tailored to the incident type.

    Args:
        incident_type: Type of incident (memory_leak, bad_deployment, api_timeout)
        service: Affected service name
        root_cause: Diagnosed root cause
        severity: Incident severity
        actions: Optional list of specific actions from Strategist

    Returns:
        Dict with crew execution results
    """
    tasks = []

    if incident_type == "memory_leak":
        tasks = [
            Task(
                description=(
                    f"Send a critical notification about the memory leak in {service}. "
                    f"Root cause: {root_cause}. Severity: {severity}. "
                    f"Notify via all channels including Slack, email, and PagerDuty."
                ),
                agent=notify_agent,
                expected_output="Confirmation that notification was sent with delivery details",
            ),
            Task(
                description=(
                    f"Scale {service} to 5 replicas to handle load while we fix the memory leak. "
                    f"Reason: incident remediation for memory leak."
                ),
                agent=scale_agent,
                expected_output="Confirmation that service was scaled with previous and new replica count",
            ),
            Task(
                description=(
                    f"Restart {service} to clear the leaked memory and restore normal operation. "
                    f"Reason: clearing memory leak - {root_cause}."
                ),
                agent=restart_agent,
                expected_output="Confirmation that service was restarted with downtime duration",
            ),
        ]

    elif incident_type == "bad_deployment":
        tasks = [
            Task(
                description=(
                    f"Send a critical notification about the bad deployment on {service}. "
                    f"Root cause: {root_cause}. Severity: {severity}."
                ),
                agent=notify_agent,
                expected_output="Confirmation that notification was sent",
            ),
            Task(
                description=(
                    f"Check the deployment history for {service} to identify the "
                    f"last known good version, then roll back to that version. "
                    f"Reason: bad deployment causing {root_cause}."
                ),
                agent=rollback_agent,
                expected_output="Confirmation of rollback with version change details",
            ),
        ]

    elif incident_type == "api_timeout":
        tasks = [
            Task(
                description=(
                    f"Send a critical notification about API timeouts on {service}. "
                    f"Root cause: {root_cause}. Multiple services may be affected."
                ),
                agent=notify_agent,
                expected_output="Confirmation that notification was sent",
            ),
            Task(
                description=(
                    f"Scale {service} to 5 replicas to handle the increased load "
                    f"from timeout retries. Reason: API timeout remediation."
                ),
                agent=scale_agent,
                expected_output="Confirmation that service was scaled",
            ),
            Task(
                description=(
                    f"Restart {service} to clear stale connections causing timeouts. "
                    f"Reason: clearing stale connections due to {root_cause}."
                ),
                agent=restart_agent,
                expected_output="Confirmation that service was restarted",
            ),
        ]

    else:
        # Generic incident
        tasks = [
            Task(
                description=(
                    f"Send a notification about the incident on {service}. "
                    f"Root cause: {root_cause}. Severity: {severity}."
                ),
                agent=notify_agent,
                expected_output="Confirmation that notification was sent",
            ),
        ]

    # Build and run the crew
    crew = Crew(
        agents=[notify_agent, scale_agent, restart_agent, rollback_agent],
        tasks=tasks,
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()

    return {
        "status": "completed",
        "incident_type": incident_type,
        "service": service,
        "tasks_executed": len(tasks),
        "crew_output": str(result),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# FULL PIPELINE: Watcher → Diagnostician → Strategist → Executor
# =============================================================================

async def full_pipeline_with_execution(service: str, scenario: str = None) -> dict:
    """Run the complete incident response pipeline including execution."""
    from agents.strategist import full_pipeline

    print(f"\n  Phases 1-3: Watcher → Diagnostician → Strategist...")
    pipeline_result = await full_pipeline(service, scenario)

    watcher = pipeline_result.get("watcher", {})
    diag = pipeline_result.get("diagnostician")
    strat = pipeline_result.get("strategist")

    if not strat:
        print(f"  No strategy produced. Stopping.")
        return pipeline_result

    # Determine incident type from diagnosis
    diagnosis = diag.get("diagnosis", {}) if diag else {}
    incident_type = diagnosis.get("root_cause_category", scenario or "unknown")
    root_cause = diag.get("root_cause", "Unknown") if diag else "Unknown"
    severity = watcher.get("severity", "high")

    print(f"\n  Phase 4: Executing remediation with CrewAI...")
    print(f"  Incident type: {incident_type}")
    print(f"  Root cause: {root_cause[:80]}")

    crew_result = build_executor_crew(
        incident_type=incident_type,
        service=service,
        root_cause=root_cause,
        severity=severity,
    )

    return {
        "watcher": watcher,
        "diagnostician": diag,
        "strategist": strat,
        "executor": crew_result,
    }


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SentinelAI Executor Crew")
    parser.add_argument("--service", default="user-service")
    parser.add_argument("--scenario", default="memory_leak")
    parser.add_argument("--full-pipeline", action="store_true",
                        help="Run complete Watcher → Diagnostician → Strategist → Executor")
    parser.add_argument("--incident-type", default=None,
                        help="Override incident type (memory_leak, bad_deployment, api_timeout)")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  SentinelAI Executor Crew (CrewAI)")
    print(f"  Service: {args.service}")
    print(f"  Scenario: {args.scenario}")
    print(f"{'='*60}")

    if args.full_pipeline:
        result = asyncio.run(full_pipeline_with_execution(args.service, args.scenario))
        crew_result = result.get("executor", {})
    else:
        # Run executor standalone with mock input
        incident_type = args.incident_type or args.scenario
        print(f"\n  Running executor crew for: {incident_type}")
        crew_result = build_executor_crew(
            incident_type=incident_type,
            service=args.service,
            root_cause=f"Test: simulated {incident_type} on {args.service}",
            severity="critical",
        )

    print(f"\n{'─'*60}")
    print(f"  EXECUTION RESULT")
    print(f"{'─'*60}")
    print(f"  Status:         {crew_result.get('status', 'N/A')}")
    print(f"  Incident Type:  {crew_result.get('incident_type', 'N/A')}")
    print(f"  Service:        {crew_result.get('service', 'N/A')}")
    print(f"  Tasks Executed: {crew_result.get('tasks_executed', 0)}")
    print(f"\n  Crew Output:")
    output = crew_result.get("crew_output", "N/A")
    # Print first 500 chars
    print(f"  {output[:500]}")
    print()