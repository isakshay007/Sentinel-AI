"""
SentinelAI — Watcher Agent
LangGraph-based anomaly detection agent that monitors services
via MCP tools and uses Groq LLM to analyze and decide.

Graph flow:
  collect_metrics → collect_logs → analyze → decide → alert (if anomaly)
"""

import json
import logging
import uuid
import asyncio
import os
from datetime import datetime, timezone
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import sys

load_dotenv()

logger = logging.getLogger(__name__)


# =============================================================================
# STATE SCHEMA
# =============================================================================

class WatcherState(TypedDict):
    # Input
    service: str
    scenario: Optional[str]
    detection_context: Optional[dict]

    # Collected data
    metrics: Optional[dict]
    metric_history: Optional[dict]
    anomaly_check: Optional[dict]
    recent_errors: Optional[list]

    # Analysis
    analysis: Optional[str]
    should_alert: bool
    confidence: float
    severity: Optional[str]
    summary: Optional[str]

    # Output
    incident_id: Optional[str]
    notification_result: Optional[dict]
    ticket_result: Optional[dict]

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
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Create a .env in the repo root (copy .env.example) "
            "or set GROQ_API_KEY in your environment / docker-compose env_file."
        )
    return ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=temperature,
        api_key=api_key,
    )


# =============================================================================
# GRAPH NODES
# =============================================================================

async def collect_metrics(state: WatcherState) -> dict:
    """Node 1: Collect current metrics, history, and anomaly status via MetricsMCP."""
    service = state["service"]
    logger.info("[WATCHER] Running for service=%s", service)
    tool_calls = state.get("tool_calls", [])
    errors = state.get("errors", [])

    args = {"service": service}
    metrics = await MCPToolCaller.call_tool(
        "mcp_servers.metrics_server", "get_current_metrics", args
    )
    tool_calls.append({
        "tool": "get_current_metrics", "server": "MetricsMCP",
        "args": args,
        "result_summary": metrics.get("health_status", "unknown")
    })

    # Call 2: Metric history (memory)
    history_args = {"service": service, "metric": "memory_percent", "minutes": 120}
    metric_history = await MCPToolCaller.call_tool(
        "mcp_servers.metrics_server", "get_metric_history", history_args
    )
    tool_calls.append({
        "tool": "get_metric_history", "server": "MetricsMCP",
        "args": history_args,
        "result_summary": f"{metric_history.get('data_points', 0)} points, trend={metric_history.get('statistics', {}).get('trend', '?')}"
    })

    # Call 3: Anomaly detection
    anomaly_args = {"service": service, "metric": "memory_percent"}
    anomaly_check = await MCPToolCaller.call_tool(
        "mcp_servers.metrics_server", "detect_anomaly", anomaly_args
    )
    tool_calls.append({
        "tool": "detect_anomaly", "server": "MetricsMCP",
        "args": anomaly_args,
        "result_summary": f"anomalous={anomaly_check.get('is_anomalous', '?')}, severity={anomaly_check.get('severity', '?')}"
    })

    return {
        "metrics": metrics,
        "metric_history": metric_history,
        "anomaly_check": anomaly_check,
        "tool_calls": tool_calls,
        "errors": errors,
    }


async def collect_logs(state: WatcherState) -> dict:
    """Node 2: Collect recent error logs via LogsMCP."""
    service = state["service"]
    tool_calls = state.get("tool_calls", [])

    recent_errors_result = await MCPToolCaller.call_tool(
        "mcp_servers.logs_server", "get_recent_errors",
        {"minutes": 60, "service": service, "include_warnings": True, "max_results": 30}
    )
    tool_calls.append({
        "tool": "get_recent_errors", "server": "LogsMCP",
        "args": {"minutes": 60, "service": service},
        "result_summary": f"{recent_errors_result.get('summary', {}).get('total_entries', 0)} entries"
    })

    log_entries = recent_errors_result.get("results", [])

    return {
        "recent_errors": log_entries,
        "tool_calls": tool_calls,
    }


async def analyze(state: WatcherState) -> dict:
    """Node 3: Groq LLM analyzes metrics + logs and produces assessment."""
    metrics = state.get("metrics", {})
    metric_history = state.get("metric_history", {})
    anomaly_check = state.get("anomaly_check", {})
    recent_errors = state.get("recent_errors", [])
    detection_context = state.get("detection_context")

    # Build context
    metrics_data = metrics.get("metrics", {})
    health_status = metrics.get("health_status", "unknown")
    warnings = metrics.get("warnings", [])
    stats = metric_history.get("statistics", {})
    evidence = anomaly_check.get("evidence", {})

    # Include detection_metrics from watcher_loop's anomaly check
    # (gives the LLM real Prometheus data even if MetricsMCP returns stale/unknown values)
    detection_section = ""
    if detection_context:
        dm = detection_context.get("detection_metrics", {})
        anomalies_list = detection_context.get("anomalies", [])
        worst = detection_context.get("worst_severity", "unknown")
        detection_section = f"""
## Anomaly Detection Results (from Prometheus via watcher_loop)
Status: {dm.get('status', 'unknown')}
CPU: {dm.get('cpu_percent', '?')}%
Memory: {dm.get('memory_percent', '?')}%
Response Time: {dm.get('response_time_ms', '?')}ms
Error Rate: {dm.get('error_rate', '?')}
Up: {dm.get('up', '?')}

## Detected Anomalies (threshold breaches)
{json.dumps(anomalies_list, indent=2)}
Worst Severity: {worst}
"""

    # Format errors (limit to 10)
    error_lines = []
    for log in recent_errors[:10]:
        error_lines.append(
            f"[{log.get('severity', '?')}] {log.get('service', '?')}: {log.get('message', '?')}"
        )
    errors_text = "\n".join(error_lines) if error_lines else "No recent errors"

    prompt = f"""You are SentinelAI Watcher, an expert DevOps monitoring agent.
Analyze the following telemetry data for service '{state["service"]}' and determine if there is a real incident.

## Current Metrics (from MetricsMCP)
Health Status: {health_status}
Warnings: {json.dumps(warnings)}
CPU: {metrics_data.get('cpu_percent', '?')}%
Memory: {metrics_data.get('memory_percent', '?')}%
Memory Used: {metrics_data.get('memory_used_mb', '?')} / {metrics_data.get('memory_total_mb', '?')} MB
Response Time: {metrics_data.get('response_time_ms', '?')}ms
Error Rate: {metrics_data.get('error_rate', '?')}
GC Pause: {metrics_data.get('gc_pause_ms', '?')}ms
{detection_section}
## Metric Trends (last 60 min)
Trend: {stats.get('trend', 'unknown')}
Change: {stats.get('change_percent', 0)}%
Min: {stats.get('min', '?')} -> Max: {stats.get('max', '?')} -> Current: {stats.get('latest', '?')}

## MCP Anomaly Detection
Is Anomalous: {anomaly_check.get('is_anomalous', '?')}
Severity: {anomaly_check.get('severity', '?')}
Evidence: {json.dumps(evidence)}

## Recent Error Logs ({len(recent_errors)} entries)
{errors_text}

IMPORTANT: If the "Anomaly Detection Results" section shows Status=down or Up=0, or if memory/CPU values exceed thresholds, this IS a real incident. Values of '?' from MetricsMCP may simply mean the service is too degraded to respond — trust the watcher_loop Prometheus data over MetricsMCP when they conflict.

Based on this data, respond with ONLY a JSON object (no other text, no markdown, no code fences):
{{
    "is_incident": true or false,
    "confidence": 0.0 to 1.0,
    "severity": "low" or "medium" or "high" or "critical",
    "summary": "One sentence description of what is happening",
    "reasoning": "2-3 sentences explaining your analysis",
    "recommended_action": "What should be done next"
}}"""

    try:
        llm = get_groq_llm(temperature=0.1)
        response = llm.invoke([HumanMessage(content=prompt)])
        analysis_text = response.content

        # Parse JSON — strip markdown fences if present
        clean = analysis_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()

        analysis = json.loads(clean)

        is_incident = analysis.get("is_incident", False)
        conf = float(analysis.get("confidence", 0.0))
        sev = analysis.get("severity", "low")
        logger.info("[WATCHER] LLM decision: is_incident=%s confidence=%.2f severity=%s", is_incident, conf, sev)
        return {
            "analysis": analysis_text,
            "should_alert": is_incident,
            "confidence": conf,
            "severity": sev,
            "summary": analysis.get("summary", "No summary available"),
        }
    except Exception as e:
        # Fallback to rule-based if LLM fails
        logger.warning("[WATCHER] LLM failed, using rule-based fallback for service=%s", state["service"])
        is_anomalous = anomaly_check.get("is_anomalous", False)
        health = metrics.get("health_status", "unknown")

        # Check detection_context for authoritative severity
        dc_worst = (detection_context or {}).get("worst_severity") if detection_context else None
        dc_status = (detection_context or {}).get("detection_metrics", {}).get("status") if detection_context else None

        if dc_worst == "critical" or dc_status == "down":
            return {
                "analysis": f"LLM failed ({e}). Rule-based critical escalation from detection context.",
                "should_alert": True,
                "confidence": 0.90,
                "severity": "critical",
                "summary": f"Critical anomaly on {state['service']} — rule-based escalation (detection_context worst_severity={dc_worst})",
                "errors": state.get("errors", []) + [f"LLM error: {str(e)}"],
            }

        fallback_alert = is_anomalous or health in ("critical", "warning")
        return {
            "analysis": f"LLM analysis failed ({e}). Falling back to rule-based.",
            "should_alert": fallback_alert,
            "confidence": 0.8 if fallback_alert else 0.2,
            "severity": anomaly_check.get("severity", "medium") if fallback_alert else "low",
            "summary": f"Rule-based: anomalous={is_anomalous}, health={health}",
            "errors": state.get("errors", []) + [f"LLM error: {str(e)}"],
        }


async def decide(state: WatcherState) -> dict:
    """Node 4: Final decision gate."""
    return {
        "should_alert": state.get("should_alert", False),
        "confidence": state.get("confidence", 0.0),
    }


async def alert(state: WatcherState) -> dict:
    """Node 5: Send notification via AlertMCP.  Ticket creation is handled by Strategist."""
    service = state["service"]
    severity = state.get("severity", "medium")
    summary = state.get("summary", "Anomaly detected")
    confidence = state.get("confidence", 0.0)
    tool_calls = state.get("tool_calls", [])

    incident_id = str(uuid.uuid4())

    notification_result = await MCPToolCaller.call_tool(
        "mcp_servers.alert_server", "send_notification",
        {
            "channel": "all" if severity in ("critical", "high") else "slack",
            "message": f"[ALERT] {summary} | Service: {service} | Severity: {severity} | Confidence: {confidence:.0%}",
            "severity": severity,
            "service": service,
            "incident_id": incident_id,
        }
    )
    tool_calls.append({
        "tool": "send_notification", "server": "AlertMCP",
        "result_summary": f"delivered_to={notification_result.get('delivered_to', '?')}"
    })

    return {
        "incident_id": incident_id,
        "ticket_result": {},
        "notification_result": notification_result,
        "tool_calls": tool_calls,
    }


# =============================================================================
# CONDITIONAL EDGE
# =============================================================================

def should_alert_router(state: WatcherState) -> str:
    if state.get("should_alert", False) and state.get("confidence", 0) >= 0.7:
        return "alert"
    return "done"


# =============================================================================
# BUILD GRAPH
# =============================================================================

def build_watcher_graph():
    graph = StateGraph(WatcherState)

    graph.add_node("collect_metrics", collect_metrics)
    graph.add_node("collect_logs", collect_logs)
    graph.add_node("analyze", analyze)
    graph.add_node("decide", decide)
    graph.add_node("alert", alert)

    graph.set_entry_point("collect_metrics")
    graph.add_edge("collect_metrics", "collect_logs")
    graph.add_edge("collect_logs", "analyze")
    graph.add_edge("analyze", "decide")

    graph.add_conditional_edges(
        "decide",
        should_alert_router,
        {"alert": "alert", "done": END}
    )
    graph.add_edge("alert", END)

    return graph.compile()


# =============================================================================
# RUN
# =============================================================================

async def run_watcher(service: str, scenario: str = None, detection_context: dict = None) -> dict:
    # ── Pre-LLM shortcut: service is DOWN ──────────────────────────
    dm = (detection_context or {}).get("detection_metrics", {})
    if dm.get("status") == "down":
        logger.info(
            "[WATCHER] Service %s is DOWN (up=0) — creating rule-based incident, skipping LLM",
            service,
        )
        incident_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        summary = (
            f"Service {service} is down — container not responding to health checks "
            f"(up metric = 0)"
        )
        tool_calls = []

        notification_result = await MCPToolCaller.call_tool(
            "mcp_servers.alert_server",
            "send_notification",
            {
                "channel": "all",
                "message": f"[ALERT] {summary} | Service: {service} | Severity: critical | Confidence: 95%",
                "severity": "critical",
                "service": service,
                "incident_id": incident_id,
            },
        )
        tool_calls.append({
            "tool": "send_notification",
            "server": "AlertMCP",
            "result_summary": f"delivered_to={notification_result.get('delivered_to', '?')}",
        })

        return {
            "service": service,
            "scenario": scenario,
            "detection_context": detection_context,
            "metrics": None,
            "metric_history": None,
            "anomaly_check": None,
            "recent_errors": None,
            "analysis": "Service is DOWN (up=0). Rule-based incident — LLM skipped.",
            "should_alert": True,
            "confidence": 0.95,
            "severity": "critical",
            "summary": summary,
            "incident_id": incident_id,
            "notification_result": notification_result,
            "ticket_result": {},
            "tool_calls": tool_calls,
            "errors": [],
            "timestamp": ts,
        }

    # ── Normal graph flow ──────────────────────────────────────────
    watcher = build_watcher_graph()

    initial_state = WatcherState(
        service=service,
        scenario=scenario,
        detection_context=detection_context,
        metrics=None,
        metric_history=None,
        anomaly_check=None,
        recent_errors=None,
        analysis=None,
        should_alert=False,
        confidence=0.0,
        severity=None,
        summary=None,
        incident_id=None,
        notification_result=None,
        ticket_result=None,
        tool_calls=[],
        errors=[],
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    final_state = await watcher.ainvoke(initial_state)
    return final_state


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SentinelAI Watcher Agent")
    parser.add_argument("--service", default="user-service")
    parser.add_argument("--scenario", default=None)
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  SentinelAI Watcher Agent")
    print(f"  Monitoring: {args.service}")
    if args.scenario:
        print(f"  Scenario:   {args.scenario}")
    print(f"{'='*55}\n")

    result = asyncio.run(run_watcher(args.service, args.scenario, detection_context=None))

    print(f"\n{'─'*55}")
    print(f"  RESULT")
    print(f"{'─'*55}")
    print(f"  Alert triggered:  {result.get('should_alert', False)}")
    print(f"  Confidence:       {result.get('confidence', 0):.0%}")
    print(f"  Severity:         {result.get('severity', 'N/A')}")
    print(f"  Summary:          {result.get('summary', 'N/A')}")

    if result.get("incident_id"):
        print(f"\n  Incident ID:      {result['incident_id'][:12]}...")
        ticket = result.get("ticket_result", {}).get("ticket", {})
        print(f"  Ticket:           {ticket.get('id', 'N/A')}")
        print(f"  Assigned to:      {ticket.get('assigned_to', 'N/A')}")
        notif = result.get("notification_result", {})
        print(f"  Notified:         {notif.get('delivered_to', 0)} recipient(s)")

    print(f"\n  MCP Tool Calls:   {len(result.get('tool_calls', []))}")
    for tc in result.get("tool_calls", []):
        print(f"    - {tc.get('server', '?')}.{tc.get('tool', '?')} -> {tc.get('result_summary', '?')}")

    if result.get("errors"):
        print(f"\n  Errors:")
        for e in result["errors"]:
            print(f"    ! {e}")

    print(f"\n  LLM Analysis:")
    print(f"  {result.get('analysis', 'N/A')[:500]}")
    print()