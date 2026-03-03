"""
SentinelAI — Diagnostician Agent
LangGraph-based root cause analysis agent using ReAct reasoning
and ChromaDB RAG for similar incident retrieval.

ReAct Loop:
  retrieve_similar → form_hypothesis → gather_evidence → evaluate →
  (if insufficient → revise_hypothesis → loop back, max 5 iterations)
  → produce_diagnosis
"""

import json
import logging
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
from rag.chroma_store import IncidentKnowledgeBase
import sys

load_dotenv()

logger = logging.getLogger(__name__)


# =============================================================================
# STATE SCHEMA
# =============================================================================

class DiagnosticianState(TypedDict):
    # Input (from Watcher)
    incident_id: str
    service: str
    scenario: Optional[str]
    watcher_summary: str
    watcher_metrics: Optional[dict]
    watcher_severity: str

    # RAG
    similar_incidents: list

    # ReAct loop state
    hypothesis: Optional[str]
    evidence: list
    evidence_summary: Optional[str]
    hypothesis_supported: Optional[bool]
    iteration: int
    max_iterations: int
    reasoning_chain: list

    # Diagnosis output
    diagnosis: Optional[dict]
    confidence: float
    root_cause: Optional[str]
    recommended_actions: list

    # Audit
    tool_calls: list
    errors: list
    timestamp: str


# =============================================================================
# MCP TOOL CALLER (reused from watcher)
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

async def retrieve_similar(state: DiagnosticianState) -> dict:
    """Node 1: Retrieve similar past incidents from ChromaDB."""
    logger.info("[DIAGNOSTICIAN] Running for service=%s", state["service"])
    kb = IncidentKnowledgeBase()
    
    # Build query from watcher findings
    query = state["watcher_summary"]
    
    # Try with service filter first
    similar = kb.query(
        symptoms=query,
        n_results=3,
        service_filter=state["service"],
    )
    
    # If too few results, broaden search
    if len(similar) < 2:
        similar = kb.query(
            symptoms=query,
            n_results=3,
        )

    reasoning_chain = state.get("reasoning_chain", [])
    reasoning_chain.append({
        "step": "retrieve_similar",
        "action": f"Retrieved {len(similar)} similar past incidents from knowledge base",
        "results": [
            {
                "title": s["metadata"].get("title", "?"),
                "similarity": s.get("similarity", 0),
                "type": s["metadata"].get("type", "?"),
            }
            for s in similar
        ],
    })

    return {
        "similar_incidents": similar,
        "reasoning_chain": reasoning_chain,
    }


async def form_hypothesis(state: DiagnosticianState) -> dict:
    """Node 2: LLM forms a hypothesis based on current data + similar incidents."""
    similar = state.get("similar_incidents", [])
    watcher_summary = state["watcher_summary"]
    watcher_metrics = state.get("watcher_metrics", {})
    iteration = state.get("iteration", 0)
    prev_hypothesis = state.get("hypothesis")
    evidence = state.get("evidence", [])

    # Format similar incidents for context
    similar_text = ""
    for i, s in enumerate(similar, 1):
        doc = s.get("document", "")
        sim = s.get("similarity", 0)
        similar_text += f"\n--- Similar Incident {i} (similarity: {sim:.1%}) ---\n{doc}\n"

    # Build prompt
    context = f"""## Watcher Alert Summary
{watcher_summary}

## Current Metrics
{json.dumps(watcher_metrics.get('metrics', {}), indent=2) if watcher_metrics else 'No metrics available'}
Health Status: {watcher_metrics.get('health_status', '?') if watcher_metrics else '?'}

## Similar Past Incidents
{similar_text if similar_text else 'No similar incidents found.'}"""

    if iteration > 0 and prev_hypothesis:
        context += f"""

## Previous Hypothesis (Iteration {iteration})
{prev_hypothesis}

## Evidence Collected So Far
{json.dumps(evidence[-3:], indent=2) if evidence else 'None'}

The previous hypothesis was NOT fully supported by evidence. Form a REVISED hypothesis."""

    prompt = f"""You are SentinelAI Diagnostician, an expert at root cause analysis for DevOps incidents.

{context}

Based on the above data, form a hypothesis about the ROOT CAUSE of this incident.
Consider the similar past incidents carefully — they provide clues about what might be happening.

Respond with ONLY a JSON object (no other text, no markdown):
{{
    "hypothesis": "Clear statement of what you think the root cause is",
    "reasoning": "2-3 sentences explaining why you formed this hypothesis",
    "evidence_needed": ["list", "of", "specific", "checks", "to", "verify"],
    "tools_to_use": ["which MCP tools would help verify this hypothesis"]
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
        hypothesis = result.get("hypothesis", "Unknown")

        reasoning_chain = state.get("reasoning_chain", [])
        reasoning_chain.append({
            "step": f"form_hypothesis (iteration {iteration + 1})",
            "hypothesis": hypothesis,
            "reasoning": result.get("reasoning", ""),
            "evidence_needed": result.get("evidence_needed", []),
        })

        return {
            "hypothesis": hypothesis,
            "iteration": iteration + 1,
            "reasoning_chain": reasoning_chain,
        }
    except Exception as e:
        # Fallback: use top similar incident as hypothesis
        fallback = "Unknown root cause"
        if similar:
            top = similar[0]
            fallback = f"Based on similar incident: {top['metadata'].get('title', 'unknown')}"

        return {
            "hypothesis": fallback,
            "iteration": iteration + 1,
            "errors": state.get("errors", []) + [f"Hypothesis LLM error: {str(e)}"],
            "reasoning_chain": state.get("reasoning_chain", []) + [{
                "step": f"form_hypothesis (iteration {iteration + 1})",
                "hypothesis": fallback,
                "note": f"Fallback due to error: {str(e)}",
            }],
        }


async def gather_evidence(state: DiagnosticianState) -> dict:
    """Node 3: Gather evidence to test the hypothesis via MCP tools."""
    service = state["service"]
    hypothesis = state.get("hypothesis", "")
    tool_calls = state.get("tool_calls", [])
    evidence = state.get("evidence", [])

    # Gather multiple types of evidence

    # Evidence 1: Search logs for clues related to hypothesis
    search_terms = ["error", "timeout", "memory", "connection", "deploy"]
    # Pick relevant search term based on hypothesis
    search_term = "error"
    hyp_lower = hypothesis.lower()
    if "memory" in hyp_lower or "leak" in hyp_lower or "oom" in hyp_lower:
        search_term = "memory"
    elif "deploy" in hyp_lower or "version" in hyp_lower or "rollback" in hyp_lower:
        search_term = "deploy"
    elif "timeout" in hyp_lower or "connection" in hyp_lower or "redis" in hyp_lower:
        search_term = "timeout"
    elif "pool" in hyp_lower or "exhaust" in hyp_lower:
        search_term = "connection"

    log_result = await MCPToolCaller.call_tool(
        "mcp_servers.logs_server", "search_logs",
        {"query": search_term, "service": service, "minutes_ago": 120, "max_results": 15}
    )
    tool_calls.append({
        "tool": "search_logs", "server": "LogsMCP",
        "args": {"query": search_term, "service": service},
        "result_summary": f"{log_result.get('total_matches', 0)} matches for '{search_term}'"
    })
    evidence.append({
        "type": "log_search",
        "query": search_term,
        "matches": log_result.get("total_matches", 0),
        "sample_logs": [
            log.get("message", "")[:100]
            for log in log_result.get("results", [])[:5]
        ],
    })

    # Evidence 2: Check multiple metrics
    for metric in ["memory_percent", "error_rate", "response_time_ms", "cpu_percent"]:
        metric_args = {"service": service, "metric": metric}
        anomaly_result = await MCPToolCaller.call_tool(
            "mcp_servers.metrics_server", "detect_anomaly", metric_args
        )
        tool_calls.append({
            "tool": "detect_anomaly", "server": "MetricsMCP",
            "args": {"service": service, "metric": metric},
            "result_summary": f"{metric}: anomalous={anomaly_result.get('is_anomalous', '?')}"
        })
        evidence.append({
            "type": "anomaly_check",
            "metric": metric,
            "is_anomalous": anomaly_result.get("is_anomalous", False),
            "severity": anomaly_result.get("severity", "normal"),
            "value": anomaly_result.get("evidence", {}).get("current_value"),
        })

    # Evidence 3: Check deployment history / container state
    deploy_result = await MCPToolCaller.call_tool(
        "mcp_servers.infra_server", "get_deployment_history",
        {"service": service}
    )
    deployment_info = deploy_result.get("deployment_info", {}) if isinstance(deploy_result, dict) else {}
    tool_calls.append({
        "tool": "get_deployment_history", "server": "InfraMCP",
        "args": {"service": service},
        "result_summary": f"status={deployment_info.get('status', '?')}, restarts={deployment_info.get('restart_count', 0)}"
    })
    evidence.append({
        "type": "deployment_history",
        # In live mode we run single-version containers; restarts are not code deploys.
        "recent_deploys": 0,
        "current_image": deployment_info.get("current_image", "?"),
        "status": deployment_info.get("status", "?"),
        "restart_count": deployment_info.get("restart_count", 0),
    })

    reasoning_chain = state.get("reasoning_chain", [])
    reasoning_chain.append({
        "step": f"gather_evidence (iteration {state.get('iteration', 1)})",
        "evidence_count": len(evidence),
        "tools_called": len(tool_calls),
    })

    return {
        "evidence": evidence,
        "tool_calls": tool_calls,
        "reasoning_chain": reasoning_chain,
    }


async def evaluate_evidence(state: DiagnosticianState) -> dict:
    """Node 4: LLM evaluates if evidence supports the hypothesis."""
    hypothesis = state.get("hypothesis", "")
    evidence = state.get("evidence", [])
    similar = state.get("similar_incidents", [])
    iteration = state.get("iteration", 1)

    # Format evidence for LLM
    evidence_text = json.dumps(evidence[-10:], indent=2)  # Last 10 pieces

    prompt = f"""You are SentinelAI Diagnostician evaluating evidence for a hypothesis.

## Current Hypothesis
{hypothesis}

## Evidence Collected
{evidence_text}

## Similar Past Incidents
{json.dumps([s['metadata'] for s in similar[:3]], indent=2) if similar else 'None'}

Evaluate whether the evidence SUPPORTS or CONTRADICTS the hypothesis.
Consider: Do the anomalous metrics align with the hypothesis? Do the logs contain clues?
Does the deployment history explain the timing?

Respond with ONLY a JSON object (no other text, no markdown):
{{
    "hypothesis_supported": true or false,
    "confidence": 0.0 to 1.0,
    "evidence_summary": "2-3 sentences summarizing what the evidence shows",
    "key_evidence": ["list", "of", "the", "most", "important", "findings"],
    "gaps": ["what", "evidence", "is", "still", "missing"],
    "should_revise": true or false
}}"""

    try:
        llm = get_groq_llm(temperature=0.1)
        response = llm.invoke([HumanMessage(content=prompt)])
        clean = response.content.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()

        result = json.loads(clean)

        reasoning_chain = state.get("reasoning_chain", [])
        reasoning_chain.append({
            "step": f"evaluate_evidence (iteration {iteration})",
            "supported": result.get("hypothesis_supported", False),
            "confidence": result.get("confidence", 0),
            "summary": result.get("evidence_summary", ""),
        })

        return {
            "hypothesis_supported": result.get("hypothesis_supported", False),
            "confidence": float(result.get("confidence", 0.0)),
            "evidence_summary": result.get("evidence_summary", ""),
            "reasoning_chain": reasoning_chain,
        }
    except Exception as e:
        # Fallback: if we have strong anomaly evidence, support the hypothesis
        anomalies = [e for e in evidence if e.get("type") == "anomaly_check" and e.get("is_anomalous")]
        fallback_supported = len(anomalies) >= 2

        return {
            "hypothesis_supported": fallback_supported,
            "confidence": 0.7 if fallback_supported else 0.4,
            "evidence_summary": f"Rule-based: {len(anomalies)} anomalous metrics found",
            "errors": state.get("errors", []) + [f"Evidence eval error: {str(e)}"],
            "reasoning_chain": state.get("reasoning_chain", []) + [{
                "step": f"evaluate_evidence (iteration {iteration})",
                "note": f"Fallback: {len(anomalies)} anomalies",
            }],
        }


async def produce_diagnosis(state: DiagnosticianState) -> dict:
    """Node 5: Produce final diagnosis with root cause and recommended actions."""
    hypothesis = state.get("hypothesis", "Unknown")
    evidence = state.get("evidence", [])
    similar = state.get("similar_incidents", [])
    confidence = state.get("confidence", 0.0)
    reasoning_chain = state.get("reasoning_chain", [])
    evidence_summary = state.get("evidence_summary", "")

    # Get resolution hints from similar incidents
    similar_resolutions = []
    for s in similar[:3]:
        doc = s.get("document", "")
        # Extract resolution line
        for line in doc.split("\n"):
            if line.startswith("Resolution:"):
                similar_resolutions.append(line.replace("Resolution: ", ""))

    prompt = f"""You are SentinelAI Diagnostician producing a final diagnosis.

## Confirmed Hypothesis
{hypothesis}

## Evidence Summary
{evidence_summary}

## Full Reasoning Chain
{json.dumps(reasoning_chain, indent=2)}

## Similar Past Resolutions
{json.dumps(similar_resolutions, indent=2) if similar_resolutions else 'No similar resolutions available'}

Produce a comprehensive diagnosis. Respond with ONLY a JSON object:
{{
    "root_cause": "Clear, specific root cause statement",
    "root_cause_category": "memory_leak" or "bad_deployment" or "api_timeout" or "configuration" or "infrastructure" or "other",
    "confidence": 0.0 to 1.0,
    "severity": "low" or "medium" or "high" or "critical",
    "impact": "Description of the impact on users and services",
    "recommended_actions": [
        {{"action": "description", "risk_level": "safe/risky/dangerous", "priority": 1}},
        {{"action": "description", "risk_level": "safe/risky/dangerous", "priority": 2}}
    ],
    "prevention": "How to prevent this in the future"
}}"""

    try:
        llm = get_groq_llm(temperature=0.1)
        response = llm.invoke([HumanMessage(content=prompt)])
        clean = response.content.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()

        diagnosis = json.loads(clean)

        # Post-LLM normalization: override root_cause_category based on actual
        # metric evidence so the label is deterministic across runs.
        anomalous_metrics = [
            e for e in evidence
            if e.get("type") == "anomaly_check" and e.get("is_anomalous")
        ]
        metric_names = {e.get("metric") for e in anomalous_metrics}
        if "memory_percent" in metric_names:
            diagnosis["root_cause_category"] = "memory_leak"
        elif "cpu_percent" in metric_names:
            diagnosis["root_cause_category"] = "cpu_overload"
        elif "response_time_ms" in metric_names:
            diagnosis["root_cause_category"] = "latency_spike"
        elif "error_rate" in metric_names:
            diagnosis["root_cause_category"] = "error_rate_spike"
        # keep LLM's label only if no metric evidence overrides it

        logger.info("[DIAGNOSTICIAN] Root cause: category=%s confidence=%.2f summary=%s",
                    diagnosis.get("root_cause_category", "?"),
                    float(diagnosis.get("confidence", 0)),
                    str(diagnosis.get("root_cause", "?"))[:200])
        reasoning_chain.append({
            "step": "produce_diagnosis",
            "root_cause": diagnosis.get("root_cause", "?"),
            "confidence": diagnosis.get("confidence", 0),
        })

        return {
            "diagnosis": diagnosis,
            "root_cause": diagnosis.get("root_cause", hypothesis),
            "confidence": float(diagnosis.get("confidence", confidence)),
            "recommended_actions": diagnosis.get("recommended_actions", []),
            "reasoning_chain": reasoning_chain,
        }
    except Exception as e:
        # Fallback diagnosis
        fallback = {
            "root_cause": hypothesis,
            "confidence": confidence,
            "severity": state.get("watcher_severity", "high"),
            "recommended_actions": [
                {"action": "Restart affected service", "risk_level": "risky", "priority": 1},
                {"action": "Investigate logs for root cause", "risk_level": "safe", "priority": 2},
            ],
        }
        return {
            "diagnosis": fallback,
            "root_cause": hypothesis,
            "confidence": confidence,
            "recommended_actions": fallback["recommended_actions"],
            "errors": state.get("errors", []) + [f"Diagnosis error: {str(e)}"],
        }


# =============================================================================
# CONDITIONAL EDGES
# =============================================================================

def should_revise_or_diagnose(state: DiagnosticianState) -> str:
    """Decide whether to revise hypothesis or produce final diagnosis."""
    supported = state.get("hypothesis_supported", False)
    confidence = state.get("confidence", 0)
    iteration = state.get("iteration", 1)
    max_iter = state.get("max_iterations", 3)

    # Produce diagnosis if:
    # 1. Hypothesis is supported with good confidence
    # 2. We've hit max iterations
    if (supported and confidence >= 0.6) or iteration >= max_iter:
        return "produce_diagnosis"
    else:
        return "revise"


# =============================================================================
# BUILD GRAPH
# =============================================================================

def build_diagnostician_graph():
    graph = StateGraph(DiagnosticianState)

    # Add nodes
    graph.add_node("retrieve_similar", retrieve_similar)
    graph.add_node("form_hypothesis", form_hypothesis)
    graph.add_node("gather_evidence", gather_evidence)
    graph.add_node("evaluate_evidence", evaluate_evidence)
    graph.add_node("produce_diagnosis", produce_diagnosis)

    # Linear flow: retrieve → hypothesize → evidence → evaluate
    graph.set_entry_point("retrieve_similar")
    graph.add_edge("retrieve_similar", "form_hypothesis")
    graph.add_edge("form_hypothesis", "gather_evidence")
    graph.add_edge("gather_evidence", "evaluate_evidence")

    # Conditional: evaluate → diagnose OR revise (loop back)
    graph.add_conditional_edges(
        "evaluate_evidence",
        should_revise_or_diagnose,
        {
            "produce_diagnosis": "produce_diagnosis",
            "revise": "form_hypothesis",  # Loop back with new hypothesis
        }
    )

    graph.add_edge("produce_diagnosis", END)

    return graph.compile()


# =============================================================================
# RUN
# =============================================================================

async def run_diagnostician(
    incident_id: str,
    service: str,
    watcher_summary: str,
    watcher_metrics: dict = None,
    watcher_severity: str = "high",
    scenario: str = None,
) -> dict:
    """Run the Diagnostician agent."""
    diagnostician = build_diagnostician_graph()

    initial_state = DiagnosticianState(
        incident_id=incident_id,
        service=service,
        scenario=scenario,
        watcher_summary=watcher_summary,
        watcher_metrics=watcher_metrics,
        watcher_severity=watcher_severity,
        similar_incidents=[],
        hypothesis=None,
        evidence=[],
        evidence_summary=None,
        hypothesis_supported=None,
        iteration=0,
        max_iterations=3,
        reasoning_chain=[],
        diagnosis=None,
        confidence=0.0,
        root_cause=None,
        recommended_actions=[],
        tool_calls=[],
        errors=[],
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    final_state = await diagnostician.ainvoke(initial_state)
    return final_state


# =============================================================================
# WATCHER → DIAGNOSTICIAN PIPELINE
# =============================================================================

async def watcher_to_diagnostician(service: str, scenario: str = None, detection_context: dict = None) -> dict:
    """Run Watcher, then feed results into Diagnostician."""
    from agents.watcher import run_watcher

    print("\n==============================")
    print("WATCHER PHASE START")
    print("==============================")
    print(f"Service: {service} | Scenario: {scenario or 'N/A'}")
    watcher_result = await run_watcher(service, scenario, detection_context=detection_context)

    if not watcher_result.get("should_alert"):
        print(f"  Watcher did not detect an incident. Skipping diagnosis.")
        return {"watcher": watcher_result, "diagnostician": None}

    incident_id = watcher_result.get("incident_id", "N/A")
    print(f"  Incident ID: {incident_id}")
    print(f"  Watcher summary: {watcher_result.get('summary', '?')[:80]}")
    print("\n==============================")
    print("DIAGNOSTICIAN PHASE START")
    print("==============================")

    diag_result = await run_diagnostician(
        incident_id=watcher_result.get("incident_id", str(uuid.uuid4())),
        service=service,
        watcher_summary=watcher_result.get("summary", "Anomaly detected"),
        watcher_metrics=watcher_result.get("metrics"),
        watcher_severity=watcher_result.get("severity", "high"),
        scenario=scenario,
    )

    return {"watcher": watcher_result, "diagnostician": diag_result}


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SentinelAI Diagnostician Agent")
    parser.add_argument("--service", default="user-service")
    parser.add_argument("--scenario", default=None)
    parser.add_argument("--full-pipeline", action="store_true",
                        help="Run Watcher → Diagnostician pipeline")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  SentinelAI Diagnostician Agent")
    print(f"  Service: {args.service}")
    if args.scenario:
        print(f"  Scenario: {args.scenario}")
    print(f"{'='*60}")

    if args.full_pipeline:
        result = asyncio.run(watcher_to_diagnostician(args.service, args.scenario))
        diag = result.get("diagnostician")
    else:
        # Run diagnostician standalone with mock watcher input
        diag = asyncio.run(run_diagnostician(
            incident_id=str(uuid.uuid4()),
            service=args.service,
            watcher_summary=f"Critical anomaly detected on {args.service}. Memory/error metrics elevated.",
            watcher_severity="critical",
            scenario=args.scenario,
        ))

    if not diag:
        print("\n  No diagnosis produced.")
    else:
        print(f"\n{'─'*60}")
        print(f"  DIAGNOSIS")
        print(f"{'─'*60}")
        print(f"  Root Cause:    {diag.get('root_cause', 'N/A')}")
        print(f"  Confidence:    {diag.get('confidence', 0):.0%}")

        diagnosis = diag.get("diagnosis", {})
        print(f"  Category:      {diagnosis.get('root_cause_category', 'N/A')}")
        print(f"  Impact:        {diagnosis.get('impact', 'N/A')}")

        actions = diag.get("recommended_actions", [])
        if actions:
            print(f"\n  Recommended Actions:")
            for a in actions:
                if isinstance(a, dict):
                    print(f"    {a.get('priority', '?')}. [{a.get('risk_level', '?')}] {a.get('action', '?')}")
                else:
                    print(f"    - {a}")

        print(f"\n  Prevention:    {diagnosis.get('prevention', 'N/A')}")

        print(f"\n  Reasoning Chain ({len(diag.get('reasoning_chain', []))} steps):")
        for step in diag.get("reasoning_chain", []):
            print(f"    > {step.get('step', '?')}")
            if 'hypothesis' in step:
                print(f"      Hypothesis: {step['hypothesis'][:80]}...")
            if 'supported' in step:
                print(f"      Supported: {step['supported']} (conf: {step.get('confidence', '?')})")

        print(f"\n  MCP Tool Calls: {len(diag.get('tool_calls', []))}")
        print(f"  Iterations:     {diag.get('iteration', '?')}")

        if diag.get("errors"):
            print(f"\n  Errors:")
            for e in diag["errors"]:
                print(f"    ! {e}")
    print()