"""
SentinelAI — Strategist Agent
LangGraph-based remediation planning agent.
Receives diagnosis, generates risk-tiered action plans,
and delegates execution via A2A protocol.

Graph flow:
  generate_plans → rank_and_tag → approval_gate → delegate_tasks
"""

import json
import uuid
import asyncio
import os
from datetime import datetime, timezone
from typing import TypedDict, Optional, List

from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import sys

load_dotenv()


# =============================================================================
# STATE SCHEMA
# =============================================================================

class StrategistState(TypedDict):
    # Input (from Diagnostician)
    incident_id: str
    service: str
    scenario: Optional[str]
    root_cause: str
    diagnosis: Optional[dict]
    diagnostician_confidence: float
    watcher_severity: str

    # Plans
    plans: list                        # List of remediation plans
    selected_plan: Optional[dict]      # The chosen plan
    actions: list                      # Individual actions from selected plan

    # Approval
    approved_actions: list             # Actions approved (auto or human)
    pending_actions: list              # Actions waiting for human approval
    rejected_actions: list             # Actions rejected

    # Delegation
    delegated_tasks: list              # Tasks sent via A2A
    execution_results: list            # Results from executors

    # Audit
    tool_calls: list
    errors: list
    timestamp: str


# =============================================================================
# MCP TOOL CALLER
# =============================================================================

class MCPToolCaller:
    @staticmethod
    async def call_tool(server_module: str, tool_name: str, args: dict) -> dict:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", server_module]
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, args)
                    response_text = result.content[0].text
                    return json.loads(response_text)
        except Exception as e:
            return {"error": str(e), "tool": tool_name}


# =============================================================================
# LLM HELPER
# =============================================================================

def get_groq_llm(temperature: float = 0.1) -> ChatGroq:
    from pathlib import Path
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(dotenv_path=env_path)
    api_key = os.getenv("GROQ_API_KEY")
    return ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=temperature,
        api_key=api_key,
    )


# =============================================================================
# GRAPH NODES
# =============================================================================

async def generate_plans(state: StrategistState) -> dict:
    """Node 1: LLM generates multiple remediation plans based on diagnosis."""
    root_cause = state["root_cause"]
    diagnosis = state.get("diagnosis", {})
    service = state["service"]
    severity = state.get("watcher_severity", "high")

    prompt = f"""You are SentinelAI Strategist, an expert at DevOps incident remediation planning.

## Incident Details
Service: {service}
Severity: {severity}
Root Cause: {root_cause}
Diagnosis Details: {json.dumps(diagnosis, indent=2) if diagnosis else 'N/A'}

Generate exactly 3 remediation plans, ranked from safest to most aggressive.
Each plan should have concrete, executable actions.

IMPORTANT: Each action must use one of these available MCP tools:
- restart_service(service, reason) — Risk: risky
- scale_service(service, replicas, reason) — Risk: safe (up) / risky (down)
- rollback_deployment(service, target_version, reason) — Risk: dangerous
- send_notification(channel, message, severity) — Risk: safe
- create_incident_ticket(title, description, priority) — Risk: safe

Respond with ONLY a JSON object (no other text, no markdown):
{{
    "plans": [
        {{
            "name": "Plan A: Conservative",
            "description": "Brief description of approach",
            "estimated_time_minutes": 10,
            "risk_level": "low",
            "actions": [
                {{
                    "step": 1,
                    "action": "Description of what to do",
                    "tool": "MCP tool name to use",
                    "tool_args": {{}},
                    "risk_level": "safe",
                    "requires_approval": false,
                    "estimated_seconds": 30
                }}
            ]
        }},
        {{
            "name": "Plan B: Moderate",
            "description": "Brief description",
            "estimated_time_minutes": 15,
            "risk_level": "medium",
            "actions": [...]
        }},
        {{
            "name": "Plan C: Aggressive",
            "description": "Brief description",
            "estimated_time_minutes": 5,
            "risk_level": "high",
            "actions": [...]
        }}
    ],
    "recommended_plan": "A" or "B" or "C",
    "reasoning": "Why you recommend this plan"
}}"""

    try:
        llm = get_groq_llm(temperature=0.2)
        response = llm.invoke([HumanMessage(content=prompt)])
        clean = response.content.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()

        result = json.loads(clean)
        plans = result.get("plans", [])
        recommended = result.get("recommended_plan", "A")

        return {
            "plans": plans,
        }
    except Exception as e:
        # Fallback: generate a basic plan
        fallback_plans = [
            {
                "name": "Plan A: Conservative — Monitor and Notify",
                "description": "Send alerts and monitor closely",
                "estimated_time_minutes": 5,
                "risk_level": "low",
                "actions": [
                    {
                        "step": 1,
                        "action": f"Send critical notification about {service}",
                        "tool": "send_notification",
                        "tool_args": {
                            "channel": "all",
                            "message": f"Incident on {service}: {root_cause}",
                            "severity": severity,
                            "service": service,
                        },
                        "risk_level": "safe",
                        "requires_approval": False,
                        "estimated_seconds": 5,
                    },
                ],
            },
            {
                "name": "Plan B: Moderate — Scale and Restart",
                "description": "Scale up then restart affected service",
                "estimated_time_minutes": 10,
                "risk_level": "medium",
                "actions": [
                    {
                        "step": 1,
                        "action": f"Scale {service} to 5 replicas for capacity",
                        "tool": "scale_service",
                        "tool_args": {
                            "service": service,
                            "replicas": 5,
                            "reason": f"Incident remediation: {root_cause}",
                        },
                        "risk_level": "safe",
                        "requires_approval": False,
                        "estimated_seconds": 30,
                    },
                    {
                        "step": 2,
                        "action": f"Restart {service} to clear bad state",
                        "tool": "restart_service",
                        "tool_args": {
                            "service": service,
                            "reason": f"Incident remediation: {root_cause}",
                        },
                        "risk_level": "risky",
                        "requires_approval": True,
                        "estimated_seconds": 15,
                    },
                ],
            },
            {
                "name": "Plan C: Aggressive — Rollback",
                "description": "Roll back to last known good version",
                "estimated_time_minutes": 5,
                "risk_level": "high",
                "actions": [
                    {
                        "step": 1,
                        "action": f"Rollback {service} to previous version",
                        "tool": "rollback_deployment",
                        "tool_args": {
                            "service": service,
                            "reason": f"Incident rollback: {root_cause}",
                        },
                        "risk_level": "dangerous",
                        "requires_approval": True,
                        "estimated_seconds": 45,
                    },
                ],
            },
        ]
        return {
            "plans": fallback_plans,
            "errors": state.get("errors", []) + [f"Plan generation error: {str(e)}"],
        }


async def rank_and_select(state: StrategistState) -> dict:
    """Node 2: Select the best plan based on severity and confidence."""
    plans = state.get("plans", [])
    severity = state.get("watcher_severity", "high")
    confidence = state.get("diagnostician_confidence", 0.5)

    if not plans:
        return {"selected_plan": None, "actions": []}

    # Selection logic based on severity and confidence
    if severity == "critical" and confidence >= 0.8:
        # High confidence critical → moderate plan (fast but not reckless)
        selected_idx = min(1, len(plans) - 1)
    elif severity == "critical":
        # Lower confidence critical → conservative first
        selected_idx = 0
    elif severity in ("high", "medium"):
        # High/medium → conservative
        selected_idx = 0
    else:
        selected_idx = 0

    selected = plans[selected_idx]

    # Extract and tag all actions
    actions = selected.get("actions", [])

    # Ensure risk tagging is correct
    for action in actions:
        tool = action.get("tool", "")
        if tool == "rollback_deployment":
            action["risk_level"] = "dangerous"
            action["requires_approval"] = True
        elif tool == "restart_service":
            action["risk_level"] = "risky"
            action["requires_approval"] = True
        elif tool in ("send_notification", "create_incident_ticket", "get_on_call_engineer"):
            action["risk_level"] = "safe"
            action["requires_approval"] = False
        elif tool == "scale_service":
            # Safe if scaling up, risky if down
            replicas = action.get("tool_args", {}).get("replicas", 2)
            action["risk_level"] = "safe" if replicas > 2 else "risky"
            action["requires_approval"] = replicas <= 2

    return {
        "selected_plan": selected,
        "actions": actions,
    }


async def approval_gate(state: StrategistState) -> dict:
    """Node 3: Sort actions into approved (safe) and pending (needs human approval)."""
    actions = state.get("actions", [])

    approved = []
    pending = []

    for action in actions:
        if action.get("requires_approval", False):
            pending.append({
                **action,
                "approval_status": "pending",
                "approval_id": str(uuid.uuid4()),
                "requested_at": datetime.now(timezone.utc).isoformat(),
            })
        else:
            approved.append({
                **action,
                "approval_status": "auto_approved",
                "approved_at": datetime.now(timezone.utc).isoformat(),
            })

    return {
        "approved_actions": approved,
        "pending_actions": pending,
        "rejected_actions": [],
    }


async def execute_safe_actions(state: StrategistState) -> dict:
    """Node 4: Execute all auto-approved (safe) actions via MCP tools."""
    approved = state.get("approved_actions", [])
    tool_calls = state.get("tool_calls", [])
    execution_results = state.get("execution_results", [])
    delegated_tasks = state.get("delegated_tasks", [])

    # Map tool names to MCP servers
    tool_server_map = {
        "send_notification": "mcp_servers.alert_server",
        "create_incident_ticket": "mcp_servers.alert_server",
        "get_on_call_engineer": "mcp_servers.alert_server",
        "scale_service": "mcp_servers.infra_server",
        "restart_service": "mcp_servers.infra_server",
        "rollback_deployment": "mcp_servers.infra_server",
        "get_deployment_history": "mcp_servers.infra_server",
        "search_logs": "mcp_servers.logs_server",
        "get_current_metrics": "mcp_servers.metrics_server",
    }

    for action in approved:
        tool = action.get("tool", "")
        tool_args = action.get("tool_args", {})
        server = tool_server_map.get(tool)

        if not server:
            execution_results.append({
                "action": action.get("action", "?"),
                "status": "skipped",
                "reason": f"Unknown tool: {tool}",
            })
            continue

        result = await MCPToolCaller.call_tool(server, tool, tool_args)

        tool_calls.append({
            "tool": tool,
            "server": server.split(".")[-1],
            "args": tool_args,
            "result_summary": result.get("status", "unknown"),
        })

        execution_results.append({
            "action": action.get("action", "?"),
            "tool": tool,
            "status": "executed",
            "risk_level": "safe",
            "result": {
                "status": result.get("status", "unknown"),
                "details": {k: v for k, v in result.items()
                           if k in ("notification_id", "ticket", "delivered_to",
                                    "result", "audit_id")},
            },
        })

        # Create A2A task record for each execution
        delegated_tasks.append({
            "task_id": str(uuid.uuid4()),
            "action": action.get("action", "?"),
            "tool": tool,
            "status": "completed",
            "risk_level": "safe",
            "executed_at": datetime.now(timezone.utc).isoformat(),
        })

    return {
        "tool_calls": tool_calls,
        "execution_results": execution_results,
        "delegated_tasks": delegated_tasks,
    }


async def create_pending_tasks(state: StrategistState) -> dict:
    """Node 5: Create A2A task records for pending (risky/dangerous) actions."""
    pending = state.get("pending_actions", [])
    delegated_tasks = state.get("delegated_tasks", [])

    for action in pending:
        delegated_tasks.append({
            "task_id": action.get("approval_id", str(uuid.uuid4())),
            "action": action.get("action", "?"),
            "tool": action.get("tool", "?"),
            "tool_args": action.get("tool_args", {}),
            "status": "awaiting_approval",
            "risk_level": action.get("risk_level", "risky"),
            "requires_approval": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    return {
        "delegated_tasks": delegated_tasks,
    }


# =============================================================================
# BUILD GRAPH
# =============================================================================

def build_strategist_graph():
    graph = StateGraph(StrategistState)

    graph.add_node("generate_plans", generate_plans)
    graph.add_node("rank_and_select", rank_and_select)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("execute_safe_actions", execute_safe_actions)
    graph.add_node("create_pending_tasks", create_pending_tasks)

    graph.set_entry_point("generate_plans")
    graph.add_edge("generate_plans", "rank_and_select")
    graph.add_edge("rank_and_select", "approval_gate")
    graph.add_edge("approval_gate", "execute_safe_actions")
    graph.add_edge("execute_safe_actions", "create_pending_tasks")
    graph.add_edge("create_pending_tasks", END)

    return graph.compile()


# =============================================================================
# RUN
# =============================================================================

async def run_strategist(
    incident_id: str,
    service: str,
    root_cause: str,
    diagnosis: dict = None,
    diagnostician_confidence: float = 0.8,
    watcher_severity: str = "high",
    scenario: str = None,
) -> dict:
    strategist = build_strategist_graph()

    initial_state = StrategistState(
        incident_id=incident_id,
        service=service,
        scenario=scenario,
        root_cause=root_cause,
        diagnosis=diagnosis,
        diagnostician_confidence=diagnostician_confidence,
        watcher_severity=watcher_severity,
        plans=[],
        selected_plan=None,
        actions=[],
        approved_actions=[],
        pending_actions=[],
        rejected_actions=[],
        delegated_tasks=[],
        execution_results=[],
        tool_calls=[],
        errors=[],
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    final_state = await strategist.ainvoke(initial_state)
    return final_state


# =============================================================================
# FULL PIPELINE: Watcher → Diagnostician → Strategist
# =============================================================================

async def full_pipeline(service: str, scenario: str = None) -> dict:
    """Run the complete incident response pipeline."""
    from agents.diagnostician import watcher_to_diagnostician

    print(f"\n  Phase 1-2: Running Watcher → Diagnostician...")
    wd_result = await watcher_to_diagnostician(service, scenario)

    watcher = wd_result.get("watcher", {})
    diag = wd_result.get("diagnostician")

    if not diag or not diag.get("root_cause"):
        print(f"  No diagnosis produced. Stopping pipeline.")
        return {"watcher": watcher, "diagnostician": diag, "strategist": None}

    print(f"  Diagnosis: {diag.get('root_cause', '?')[:80]}")
    print(f"\n  Phase 3: Running Strategist...")

    strat_result = await run_strategist(
        incident_id=watcher.get("incident_id", str(uuid.uuid4())),
        service=service,
        root_cause=diag.get("root_cause", "Unknown"),
        diagnosis=diag.get("diagnosis"),
        diagnostician_confidence=diag.get("confidence", 0.5),
        watcher_severity=watcher.get("severity", "high"),
        scenario=scenario,
    )

    return {
        "watcher": watcher,
        "diagnostician": diag,
        "strategist": strat_result,
    }


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SentinelAI Strategist Agent")
    parser.add_argument("--service", default="user-service")
    parser.add_argument("--scenario", default=None)
    parser.add_argument("--full-pipeline", action="store_true")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  SentinelAI Strategist Agent")
    print(f"  Service: {args.service}")
    if args.scenario:
        print(f"  Scenario: {args.scenario}")
    print(f"{'='*60}")

    if args.full_pipeline:
        result = asyncio.run(full_pipeline(args.service, args.scenario))
        strat = result.get("strategist")
    else:
        strat = asyncio.run(run_strategist(
            incident_id=str(uuid.uuid4()),
            service=args.service,
            root_cause=f"Memory leak in {args.service} connection pool",
            watcher_severity="critical",
            diagnostician_confidence=0.8,
            scenario=args.scenario,
        ))

    if not strat:
        print("\n  No strategy produced.")
    else:
        print(f"\n{'─'*60}")
        print(f"  STRATEGY")
        print(f"{'─'*60}")

        selected = strat.get("selected_plan", {})
        print(f"  Selected Plan: {selected.get('name', 'N/A')}")
        print(f"  Description:   {selected.get('description', 'N/A')}")
        print(f"  Risk Level:    {selected.get('risk_level', 'N/A')}")
        print(f"  Est. Time:     {selected.get('estimated_time_minutes', '?')} min")

        print(f"\n  All Plans Generated:")
        for i, plan in enumerate(strat.get("plans", [])):
            marker = " <<<" if plan.get("name") == selected.get("name") else ""
            print(f"    {i+1}. {plan.get('name', '?')} (risk: {plan.get('risk_level', '?')}){marker}")

        approved = strat.get("approved_actions", [])
        pending = strat.get("pending_actions", [])
        print(f"\n  Actions: {len(approved)} auto-approved, {len(pending)} pending approval")

        if approved:
            print(f"\n  Auto-Executed (safe):")
            for a in approved:
                print(f"    ✓ [{a.get('risk_level', '?')}] {a.get('action', '?')}")

        if pending:
            print(f"\n  Awaiting Human Approval:")
            for a in pending:
                print(f"    ⏳ [{a.get('risk_level', '?')}] {a.get('action', '?')}")
                print(f"       Approval ID: {a.get('approval_id', '?')[:12]}...")

        results = strat.get("execution_results", [])
        if results:
            print(f"\n  Execution Results:")
            for r in results:
                print(f"    - {r.get('action', '?')[:60]}: {r.get('status', '?')}")

        tasks = strat.get("delegated_tasks", [])
        print(f"\n  A2A Tasks: {len(tasks)}")
        for t in tasks:
            print(f"    [{t.get('status', '?')}] {t.get('action', '?')[:60]}")

        print(f"\n  MCP Tool Calls: {len(strat.get('tool_calls', []))}")

        if strat.get("errors"):
            print(f"\n  Errors:")
            for e in strat["errors"]:
                print(f"    ! {e}")
    print()