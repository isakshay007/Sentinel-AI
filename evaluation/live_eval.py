"""
SentinelAI — Live Evaluation Pipeline

End-to-end evaluation that injects real chaos into running Docker
containers, watches the multi-agent pipeline respond, collects
empirical performance metrics, and generates an LLM-powered report.

Flow:
  1. Inject fault via /api/chaos/inject
  2. Poll for incident detection
  3. Poll for diagnosis (agent decisions)
  4. Auto-approve pending actions
  5. Poll for resolution
  6. Stop chaos + wait for stabilisation
  7. Collect timing metrics
  8. Generate Groq LLM markdown report
  9. Save latest_eval.json + latest_report.md

Usage:
  python -m evaluation.live_eval                      # Run all scenarios
  python -m evaluation.live_eval --scenario memory_leak  # One scenario
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("live_eval")

API_BASE = os.getenv("EVAL_API_BASE", "http://localhost:8000")
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# --- Scenario Definitions (All 5 Fault Types) --------------------------------
LIVE_SCENARIOS = [
    {
        "name": "memory_leak",
        "target": "user-service",
        "type": "memory_leak",
        "intensity": 90,
        "duration": 350,
        "expected_root_cause": "memory_leak",
        "description": "Memory leak on user-service - tests detection of memory pressure, diagnosis accuracy, and restart remediation.",
    },
    {
        "name": "cpu_spike",
        "target": "payment-service",
        "type": "cpu_spike",
        "intensity": 90,
        "duration": 350,
        "expected_root_cause": "cpu_overload",
        "description": "CPU spike on payment-service - tests detection of compute saturation and scaling response.",
    },
    {
        "name": "kill_service",
        "target": "user-service",
        "type": "kill_service",
        "intensity": 100,
        "duration": 350,
        "expected_root_cause": "service_down",
        "description": "Kill user-service container - tests detection of service unavailability and restart remediation.",
    },
    {
        "name": "network_latency",
        "target": "api-gateway",
        "type": "network_latency",
        "intensity": 80,
        "duration": 350,
        "expected_root_cause": "latency_spike",
        "description": "Network latency on api-gateway - tests detection of slow responses and diagnosis of network issues.",
    },
    {
        "name": "cache_failure",
        "target": "redis",
        "type": "cache_failure",
        "intensity": 100,
        "duration": 350,
        "expected_root_cause": "service_down|error_rate_spike|cache_failure",
        "description": "Redis cache failure - tests detection of cache unavailability and cascading effects.",
    },
]

# --- Timeouts & polling ------------------------------------------------------
DETECTION_TIMEOUT = 300     # seconds to wait for incident detection
DIAGNOSIS_TIMEOUT = 120     # seconds to wait for diagnosis decision
RESOLUTION_TIMEOUT = 180    # seconds to wait for incident resolution
APPROVAL_POLL_INTERVAL = 5  # seconds between approval checks
STABILISE_WAIT = 45         # seconds to wait between scenarios
POLL_INTERVAL = 5           # general polling interval


# =============================================================================
# HTTP HELPERS
# =============================================================================

def _api(method: str, path: str, **kwargs) -> dict:
    """Make an API call to the backend. Returns parsed JSON or error dict."""
    url = f"{API_BASE}{path}"
    try:
        with httpx.Client(timeout=30) as client:
            resp = getattr(client, method)(url, **kwargs)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}", "detail": e.response.text[:200]}
    except Exception as e:
        return {"error": str(e)}


def api_get(path: str) -> dict:
    return _api("get", path)


def api_post(path: str, body: dict = None) -> dict:
    return _api("post", path, json=body or {})


# =============================================================================
# SCENARIO RUNNER
# =============================================================================

def run_scenario(scenario: dict) -> dict:
    """
    Execute a single evaluation scenario:
      inject -> detect -> diagnose -> approve -> resolve -> cleanup
    Returns a result dict with timing metrics and outcomes.
    """
    name = scenario["name"]
    target = scenario["target"]
    ts = lambda: datetime.now(timezone.utc)

    result = {
        "scenario": name,
        "target": target,
        "description": scenario.get("description", ""),
        "expected_root_cause": scenario.get("expected_root_cause", ""),
        "started_at": ts().isoformat(),

        # Timing (seconds)
        "detection_time_s": None,
        "diagnosis_time_s": None,
        "resolution_time_s": None,
        "total_time_s": None,

        # Outcomes
        "incident_detected": False,
        "incident_id": None,
        "root_cause_found": None,
        "root_cause_correct": False,
        "diagnosis_confidence": None,
        "tools_used": [],
        "tool_count": 0,
        "alert_triggered": False,
        "resolution_status": None,
        "auto_approved": False,
        "approval_count": 0,

        # Errors
        "errors": [],
    }

    t_start = time.time()

    # -- Step 1: Inject fault -------------------------------------------------
    logger.info("[%s] Injecting %s on %s (intensity=%s, duration=%ss)",
                name, scenario["type"], target, scenario["intensity"], scenario["duration"])
    inject_resp = api_post("/api/chaos/inject", {
        "target": target,
        "type": scenario["type"],
        "intensity": scenario["intensity"],
        "duration": scenario["duration"],
    })
    if "error" in inject_resp:
        result["errors"].append(f"Injection failed: {inject_resp}")
        logger.error("[%s] Injection failed: %s", name, inject_resp)
        return result

    t_injected = time.time()
    logger.info("[%s] Fault injected. Waiting for detection...", name)

    # -- Step 2: Wait for incident detection ----------------------------------
    incident_id = None
    deadline = time.time() + DETECTION_TIMEOUT
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        incidents = api_get("/api/incidents")
        for inc in incidents.get("incidents", []):
            meta = inc.get("metadata") or {}
            if meta.get("service") == target:
                incident_id = inc["id"]
                break
        if incident_id:
            break

    if not incident_id:
        result["errors"].append("Detection timeout - no incident created")
        logger.warning("[%s] Detection timeout after %ds", name, DETECTION_TIMEOUT)
        _stop_chaos(target, name)
        return result

    t_detected = time.time()
    result["incident_detected"] = True
    result["incident_id"] = incident_id
    result["alert_triggered"] = True
    result["detection_time_s"] = round(t_detected - t_injected, 1)
    logger.info("[%s] Incident detected: %s (%.1fs)", name, incident_id[:12], result["detection_time_s"])

    # -- Step 3: Wait for diagnosis -------------------------------------------
    diagnosis_decision = None
    deadline = time.time() + DIAGNOSIS_TIMEOUT
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        decisions = api_get("/api/agent-decisions?limit=20")
        for d in decisions.get("decisions", []):
            if d.get("incident_id") == incident_id and d.get("agent_name") == "diagnostician":
                diagnosis_decision = d
                break
        if diagnosis_decision:
            break

    if diagnosis_decision:
        t_diagnosed = time.time()
        result["diagnosis_time_s"] = round(t_diagnosed - t_detected, 1)

        # Parse reasoning for root cause
        reasoning = diagnosis_decision.get("reasoning", "")
        if isinstance(reasoning, str):
            try:
                reasoning = json.loads(reasoning)
            except (json.JSONDecodeError, TypeError):
                pass

        if isinstance(reasoning, dict):
            # diagnostician_db stores: {root_cause, diagnosis: {root_cause_category, ...}, ...}
            diag_inner = reasoning.get("diagnosis")
            if isinstance(diag_inner, dict):
                result["root_cause_found"] = (
                    diag_inner.get("root_cause_category")
                    or diag_inner.get("root_cause")
                    or reasoning.get("root_cause")
                    or "unknown"
                )
            else:
                result["root_cause_found"] = (
                    reasoning.get("root_cause_category")
                    or reasoning.get("root_cause")
                    or "unknown"
                )
        else:
            result["root_cause_found"] = str(reasoning)[:200]

        result["diagnosis_confidence"] = diagnosis_decision.get("confidence")

        # Check accuracy
        expected = scenario.get("expected_root_cause", "")
        found = str(result["root_cause_found"]).lower()
        result["root_cause_correct"] = any(
            alt.strip().lower() in found
            for alt in expected.split("|")
        ) if expected else False

        logger.info("[%s] Diagnosis: %s (confidence=%.0f%%, correct=%s, %.1fs)",
                    name, result["root_cause_found"],
                    (result["diagnosis_confidence"] or 0) * 100,
                    result["root_cause_correct"],
                    result["diagnosis_time_s"])
    else:
        logger.warning("[%s] Diagnosis timeout after %ds", name, DIAGNOSIS_TIMEOUT)
        result["errors"].append("Diagnosis timeout")

    # -- Step 4: Collect tool calls -------------------------------------------
    all_decisions = api_get("/api/agent-decisions?limit=50")
    tools = []
    for d in all_decisions.get("decisions", []):
        if d.get("incident_id") == incident_id:
            for tc in (d.get("tool_calls") or []):
                if isinstance(tc, dict):
                    tools.append(tc.get("tool", "unknown"))
                elif isinstance(tc, str):
                    tools.append(tc)
    result["tools_used"] = tools
    result["tool_count"] = len(tools)

    # -- Step 5: Auto-approve pending actions ---------------------------------
    approval_count = 0
    deadline = time.time() + 30  # give 30s for approvals to appear
    while time.time() < deadline:
        time.sleep(APPROVAL_POLL_INTERVAL)
        approvals = api_get("/api/approvals")
        pending = [
            a for a in approvals.get("approvals", [])
            if a.get("incident_id") == incident_id and a.get("status") == "pending"
        ]
        if not pending:
            if approval_count > 0:
                break  # We already approved some and none are left
            continue  # Still waiting for approvals to appear

        for a in pending:
            aid = a["id"]
            logger.info("[%s] Auto-approving: %s (%s)", name, a.get("tool", "?"), aid[:12])
            approve_resp = api_post(f"/api/approve/{aid}", {
                "decided_by": "live_eval",
                "reason": "Auto-approved by live evaluation runner",
            })
            if "error" not in approve_resp:
                approval_count += 1
            else:
                result["errors"].append(f"Approve failed for {aid[:12]}: {approve_resp}")

    result["auto_approved"] = approval_count > 0
    result["approval_count"] = approval_count
    if approval_count:
        logger.info("[%s] Auto-approved %d action(s)", name, approval_count)

    # -- Step 6: Wait for resolution ------------------------------------------
    t_pre_resolve = time.time()
    deadline = time.time() + RESOLUTION_TIMEOUT
    resolved = False
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        incidents = api_get(f"/api/incidents")
        for inc in incidents.get("incidents", []):
            if inc.get("id") == incident_id:
                if inc.get("status") == "resolved":
                    resolved = True
                break
        if resolved:
            break

    t_resolved = time.time()
    if resolved:
        result["resolution_time_s"] = round(t_resolved - t_pre_resolve, 1)
        result["resolution_status"] = "resolved"
        logger.info("[%s] Incident resolved (%.1fs)", name, result["resolution_time_s"])
    else:
        result["resolution_status"] = "timeout"
        result["errors"].append("Resolution timeout")
        logger.warning("[%s] Resolution timeout", name)

    # -- Step 7: Stop chaos + cleanup -----------------------------------------
    _stop_chaos(target, name)

    result["total_time_s"] = round(time.time() - t_start, 1)
    result["completed_at"] = ts().isoformat()

    return result


def _stop_chaos(target: str, scenario_name: str):
    """Stop chaos on a target service."""
    logger.info("[%s] Stopping chaos on %s", scenario_name, target)
    resp = api_post("/api/chaos/stop", {"target": target})
    if "error" in resp:
        logger.warning("[%s] Chaos stop failed: %s (may have auto-expired)", scenario_name, resp)
    else:
        logger.info("[%s] Chaos stopped on %s", scenario_name, target)


def _wait_for_stabilisation(seconds: int):
    """Wait for services to stabilise between scenarios."""
    logger.info("Waiting %ds for services to stabilise...", seconds)
    time.sleep(seconds)


# =============================================================================
# LLM REPORT GENERATION
# =============================================================================

def generate_llm_report(results: list[dict], overall: dict) -> str:
    """Use Groq LLM to generate a human-readable markdown evaluation report."""
    try:
        from langchain_groq import ChatGroq
        from langchain_core.messages import HumanMessage

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            logger.warning("GROQ_API_KEY not set - generating template report instead")
            return _template_report(results, overall)

        llm = ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=0.3,
            api_key=api_key,
        )

        prompt = f"""You are an AI evaluation analyst for SentinelAI, a multi-agent DevOps incident response system.

Generate a professional markdown evaluation report based on these live test results.

## Raw Results
{json.dumps(results, indent=2)}

## Overall Summary
{json.dumps(overall, indent=2)}

Write the report in this format:

# SentinelAI - Live Evaluation Report

**Date:** [timestamp]
**Scenarios tested:** [count]
**Overall Score:** [score]%

## Executive Summary
[2-3 sentences about overall performance]

## Scenario Results

### [Scenario Name]
- **Target:** [service]
- **Detection Time:** [Xs]
- **Diagnosis Time:** [Xs]
- **Resolution Time:** [Xs]
- **Root Cause Accuracy:** [correct/incorrect - expected vs found]
- **Tools Used:** [count]
- **Auto-Approved Actions:** [count]
- **Status:** RESOLVED / FAILED

[1-2 sentences of analysis]

(repeat for each scenario)

## Performance Analysis
[Analyze detection speed, diagnosis accuracy, resolution effectiveness]

## Strengths
[Bullet points of what worked well]

## Areas for Improvement
[Bullet points of what could be better]

## Recommendations
[Actionable items]

---
*Generated by SentinelAI Live Evaluation Pipeline*
"""

        response = llm.invoke([HumanMessage(content=prompt)])
        return response.content

    except Exception as e:
        logger.warning("LLM report generation failed: %s - using template", e)
        return _template_report(results, overall)


def _template_report(results: list[dict], overall: dict) -> str:
    """Fallback template report when LLM is unavailable."""
    lines = [
        "# SentinelAI - Live Evaluation Report",
        "",
        f"**Date:** {overall.get('timestamp', 'N/A')}",
        f"**Scenarios tested:** {overall.get('scenarios_run', 0)}",
        f"**Overall Score:** {overall.get('overall_score', 0):.0%}",
        "",
        "## Scenario Results",
        "",
    ]

    for r in results:
        status = "RESOLVED" if r.get("resolution_status") == "resolved" else "FAILED"
        accuracy = "CORRECT" if r.get("root_cause_correct") else "INCORRECT"
        lines.extend([
            f"### {r['scenario']}",
            f"- **Target:** {r.get('target', '?')}",
            f"- **Detection Time:** {r.get('detection_time_s', '?')}s",
            f"- **Diagnosis Time:** {r.get('diagnosis_time_s', '?')}s",
            f"- **Resolution Time:** {r.get('resolution_time_s', '?')}s",
            f"- **Root Cause:** {r.get('root_cause_found', '?')} ({accuracy})",
            f"- **Tools Used:** {r.get('tool_count', 0)}",
            f"- **Status:** {status}",
            "",
        ])

    lines.extend([
        "---",
        "*Generated by SentinelAI Live Evaluation Pipeline (template mode)*",
    ])
    return "\n".join(lines)


# =============================================================================
# SCORING
# =============================================================================

def score_scenario(result: dict) -> float:
    """Score a single scenario result from 0.0 to 1.0."""
    score = 0.0
    weights = 0.0

    # Detection (30% weight)
    if result.get("incident_detected"):
        dt = result.get("detection_time_s")
        if dt is not None:
            # Perfect if < 30s, degrades linearly to 0 at 120s
            detection_score = max(0, 1.0 - (dt - 30) / 90)
            score += 0.30 * min(1.0, detection_score)
        else:
            score += 0.15  # Detected but no timing
    weights += 0.30

    # Diagnosis accuracy (30% weight)
    if result.get("root_cause_correct"):
        score += 0.30
    elif result.get("root_cause_found"):
        score += 0.10  # Partial credit for finding something
    weights += 0.30

    # Resolution (25% weight)
    if result.get("resolution_status") == "resolved":
        rt = result.get("resolution_time_s")
        if rt is not None:
            resolution_score = max(0, 1.0 - (rt - 10) / 110)
            score += 0.25 * min(1.0, resolution_score)
        else:
            score += 0.15
    weights += 0.25

    # Tools efficiency (15% weight)
    tc = result.get("tool_count", 0)
    if tc > 0:
        # Optimal is 6-12 tool calls (watcher + diagnostician + executor)
        if 4 <= tc <= 15:
            score += 0.15
        elif tc < 4:
            score += 0.05  # Too few tools
        else:
            score += 0.10  # Too many but still working
    weights += 0.15

    return round(score / weights if weights > 0 else 0, 3)


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="SentinelAI Live Evaluation Pipeline")
    parser.add_argument("--scenario", default=None, help="Run a specific scenario (e.g. memory_leak)")
    parser.add_argument("--api-base", default=None, help="Backend API base URL (default: http://localhost:8000)")
    args = parser.parse_args()

    if args.api_base:
        global API_BASE
        API_BASE = args.api_base

    # Select scenarios
    if args.scenario:
        scenarios = [s for s in LIVE_SCENARIOS if s["name"] == args.scenario]
        if not scenarios:
            logger.error("Unknown scenario: %s (available: %s)",
                        args.scenario, [s["name"] for s in LIVE_SCENARIOS])
            sys.exit(1)
    else:
        scenarios = LIVE_SCENARIOS

    # Verify backend is reachable
    logger.info("=" * 60)
    logger.info("  SentinelAI Live Evaluation Pipeline")
    logger.info("  API: %s", API_BASE)
    logger.info("  Scenarios: %s", [s["name"] for s in scenarios])
    logger.info("=" * 60)

    health = api_get("/api/services/health")
    if "error" in health:
        logger.error("Cannot reach backend at %s - is Docker stack running?", API_BASE)
        logger.error("   Error: %s", health["error"])
        sys.exit(1)

    services = health.get("services", [])
    logger.info("Backend reachable. %d services reporting.", len(services))

    # Run scenarios
    all_results = []
    for i, scenario in enumerate(scenarios):
        logger.info("")
        logger.info("-" * 60)
        logger.info("  SCENARIO %d/%d: %s", i + 1, len(scenarios), scenario["name"])
        logger.info("-" * 60)

        result = run_scenario(scenario)
        result["score"] = score_scenario(result)
        all_results.append(result)

        logger.info("[%s] Score: %.0f%%", scenario["name"], result["score"] * 100)

        # Stabilise between scenarios
        if i < len(scenarios) - 1:
            _wait_for_stabilisation(STABILISE_WAIT)

    # -- Final cleanup - stop all chaos ---------------------------------------
    logger.info("")
    logger.info("Final cleanup - stopping chaos on all targets...")
    for scenario in scenarios:
        _stop_chaos(scenario["target"], "cleanup")

    # -- Build overall summary ------------------------------------------------
    scores = [r["score"] for r in all_results]
    overall_score = sum(scores) / len(scores) if scores else 0

    overall = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scenarios_run": len(all_results),
        "overall_score": round(overall_score, 3),
        "model": "groq/llama-3.1-8b-instant",
        "scenarios": all_results,
    }

    # -- Generate LLM report --------------------------------------------------
    logger.info("")
    logger.info("Generating LLM evaluation report...")
    report_md = generate_llm_report(all_results, overall)

    # -- Save results ---------------------------------------------------------
    json_path = RESULTS_DIR / "latest_eval.json"
    report_path = RESULTS_DIR / "latest_report.md"

    with open(json_path, "w") as f:
        json.dump(overall, f, indent=2)
    logger.info("Saved: %s", json_path)

    with open(report_path, "w") as f:
        f.write(report_md)
    logger.info("Saved: %s", report_path)

    # Also save a timestamped copy
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    ts_json = RESULTS_DIR / f"live_eval_{ts_str}.json"
    with open(ts_json, "w") as f:
        json.dump(overall, f, indent=2)

    # -- Print summary --------------------------------------------------------
    logger.info("")
    logger.info("=" * 60)
    logger.info("  EVALUATION COMPLETE")
    logger.info("=" * 60)
    logger.info("  Overall Score: %.0f%%", overall_score * 100)
    for r in all_results:
        status = "[PASS]" if r.get("resolution_status") == "resolved" else "[FAIL]"
        accuracy = "[CORRECT]" if r.get("root_cause_correct") else "[WRONG]"
        logger.info("  %s  %-15s  score=%.0f%%  detect=%ss  diagnose=%ss  resolve=%ss  root_cause=%s %s",
                    status, r["scenario"],
                    r["score"] * 100,
                    r.get("detection_time_s", "N/A"),
                    r.get("diagnosis_time_s", "N/A"),
                    r.get("resolution_time_s", "N/A"),
                    r.get("root_cause_found", "N/A"),
                    accuracy)
    logger.info("")
    logger.info("  Results:  %s", json_path)
    logger.info("  Report:   %s", report_path)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()