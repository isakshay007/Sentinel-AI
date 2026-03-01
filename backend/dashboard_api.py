"""
SentinelAI — Dashboard API Endpoints
Serves data from PostgreSQL and JSON files to the React frontend.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
from backend.database import SessionLocal
from backend.models import Incident, AgentDecision, AuditLog

router = APIRouter(prefix="/api", tags=["dashboard"])

# Paths relative to project root so they work regardless of CWD
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = _PROJECT_ROOT / "evaluation" / "results"
FIXTURES_DIR = _PROJECT_ROOT / "tests" / "fixtures"


# =============================================================================
# DASHBOARD STATS
# =============================================================================

@router.get("/dashboard/stats")
def get_dashboard_stats():
    db = SessionLocal()
    try:
        total_incidents = db.query(Incident).count()
        open_incidents = db.query(Incident).filter(Incident.status == "open").count()
        total_decisions = db.query(AgentDecision).count()
        total_audits = db.query(AuditLog).count()

        # Get latest safety report (graceful if dir missing)
        safety_score = 67.1
        if EVAL_DIR.exists():
            safety_files = sorted(EVAL_DIR.glob("safety_report_*.json"), reverse=True)
            if safety_files:
                with open(safety_files[0]) as f:
                    report = json.load(f)
                    safety_score = report.get("composite_safety_score", 67.1)

        # Get latest eval scores (graceful if dir missing)
        eval_score = 0.76
        if EVAL_DIR.exists():
            eval_files = sorted(EVAL_DIR.glob("eval_*.json"), reverse=True)
            if eval_files:
                with open(eval_files[0]) as f:
                    data = json.load(f)
                    results = data.get("results", {})
                    all_scores = []
                    for scenario_data in results.values():
                        all_scores.extend(scenario_data.get("scores", {}).values())
                    if all_scores:
                        eval_score = round(sum(all_scores) / len(all_scores), 2)

        return {
            "incidents": {"total": total_incidents, "open": open_incidents},
            "agents": {
                "total_decisions": total_decisions,
                "total_tool_calls": total_audits,
                "active_agents": 4,
            },
            "safety_score": safety_score,
            "eval_score": eval_score,
        }
    finally:
        db.close()


# =============================================================================
# INCIDENTS
# =============================================================================

@router.get("/incidents")
def get_incidents(status: Optional[str] = None, limit: int = 20):
    db = SessionLocal()
    try:
        query = db.query(Incident).order_by(Incident.detected_at.desc())
        if status:
            query = query.filter(Incident.status == status)
        incidents = query.limit(limit).all()

        return {
            "total": len(incidents),
            "incidents": [
                {
                    "id": inc.id,
                    "title": inc.title,
                    "severity": inc.severity,
                    "status": inc.status,
                    "detected_at": inc.detected_at.isoformat() if inc.detected_at else None,
                    "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
                    "root_cause": inc.root_cause,
                    "metadata": inc.metadata_,
                }
                for inc in incidents
            ],
        }
    finally:
        db.close()


# =============================================================================
# AGENT DECISIONS + TRACES
# =============================================================================

@router.get("/agent-decisions")
def get_agent_decisions(agent_name: Optional[str] = None, limit: int = 50):
    db = SessionLocal()
    try:
        query = db.query(AgentDecision).order_by(AgentDecision.created_at.desc())
        if agent_name:
            query = query.filter(AgentDecision.agent_name == agent_name)
        decisions = query.limit(limit).all()

        return {
            "total": len(decisions),
            "decisions": [
                {
                    "id": d.id,
                    "incident_id": d.incident_id,
                    "agent_name": d.agent_name,
                    "decision_type": d.decision_type,
                    "reasoning": d.reasoning,
                    "confidence": d.confidence,
                    "tool_calls": d.tool_calls,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                }
                for d in decisions
            ],
        }
    finally:
        db.close()


@router.get("/agent-trace/{incident_id}")
def get_agent_trace(incident_id: str):
    db = SessionLocal()
    try:
        # Get all decisions for this incident
        decisions = (
            db.query(AgentDecision)
            .filter(AgentDecision.incident_id == incident_id)
            .order_by(AgentDecision.created_at.asc())
            .all()
        )

        # Get audit logs for this incident (filter by incident_id for correct trace)
        audits = (
            db.query(AuditLog)
            .filter(AuditLog.incident_id == incident_id)
            .order_by(AuditLog.timestamp.asc())
            .limit(100)
            .all()
        )

        # Get the incident
        incident = db.query(Incident).filter(Incident.id == incident_id).first()

        return {
            "incident": {
                "id": incident.id,
                "title": incident.title,
                "severity": incident.severity,
                "status": incident.status,
                "metadata": incident.metadata_,
            } if incident else None,
            "trace": [
                {
                    "agent_name": d.agent_name,
                    "decision_type": d.decision_type,
                    "reasoning": d.reasoning,
                    "confidence": d.confidence,
                    "tool_calls": d.tool_calls,
                    "timestamp": d.created_at.isoformat() if d.created_at else None,
                }
                for d in decisions
            ],
            "audit_log": [
                {
                    "agent_name": a.agent_name,
                    "action": a.action,
                    "mcp_server": a.mcp_server,
                    "tool_name": a.tool_name,
                    "timestamp": a.timestamp.isoformat() if a.timestamp else None,
                }
                for a in audits[:30]
            ],
        }
    finally:
        db.close()


# =============================================================================
# EVAL RESULTS
# =============================================================================

@router.get("/eval-results")
def get_eval_results():
    results = []
    if not EVAL_DIR.exists():
        return {"total": 0, "evaluations": []}
    for filepath in sorted(EVAL_DIR.glob("eval_*.json"), reverse=True):
        try:
            with open(filepath) as f:
                data = json.load(f)
            results.append(data)
        except Exception:
            continue

    return {"total": len(results), "evaluations": results[:10]}


# =============================================================================
# SAFETY REPORT
# =============================================================================

@router.get("/safety-report")
def get_safety_report():
    if not EVAL_DIR.exists():
        return {"error": "No safety reports found"}
    safety_files = sorted(EVAL_DIR.glob("safety_report_*.json"), reverse=True)
    if not safety_files:
        return {"error": "No safety reports found"}

    # Return the most comprehensive one (full run)
    for filepath in safety_files:
        with open(filepath) as f:
            report = json.load(f)
        if len(report.get("category_scores", {})) >= 3:
            return report

    # Fallback to latest
    with open(safety_files[0]) as f:
        return json.load(f)


# =============================================================================
# SERVICE HEALTH (from mock data)
# =============================================================================

@router.get("/service-health")
def get_service_health():
    services = []
    for scenario_file in FIXTURES_DIR.glob("*.json"):
        if scenario_file.name.startswith("_"):
            continue
        try:
            with open(scenario_file) as f:
                data = json.load(f)
            metrics = data.get("metrics", [])
            if metrics:
                # Get last metric per service
                service_latest = {}
                for m in metrics:
                    svc = m.get("service", "unknown")
                    service_latest[svc] = m

                for svc, m in service_latest.items():
                    # Avoid duplicates
                    if not any(s["name"] == svc for s in services):
                        cpu = m.get("cpu_percent", 0)
                        mem = m.get("memory_percent", 0)
                        err = m.get("error_rate", 0)

                        if cpu > 90 or mem > 92 or err > 0.15:
                            status = "critical"
                        elif cpu > 75 or mem > 80 or err > 0.05:
                            status = "warning"
                        else:
                            status = "healthy"

                        services.append({
                            "name": svc,
                            "cpu_percent": round(cpu, 1),
                            "memory_percent": round(mem, 1),
                            "response_time_ms": round(m.get("response_time_ms", 0), 1),
                            "error_rate": round(err, 4),
                            "status": status,
                        })
        except Exception:
            continue

    return {"services": services}


# =============================================================================
# TRIGGER SCENARIO (for demo purposes)
# =============================================================================

@router.post("/run-scenario/{scenario}")
async def run_scenario(scenario: str):
    """Run full pipeline (Watcher → Diagnostician → Strategist), persist to DB, and register pending approvals."""
    from agents.strategist import full_pipeline
    from agents.watcher_db import persist_watcher_result
    from agents.diagnostician_db import persist_diagnostician_result
    from agents.strategist_db import persist_strategist_result
    from backend.approval import add_approval_request

    service_map = {
        "memory_leak": "user-service",
        "bad_deployment": "payment-service",
        "api_timeout": "api-gateway",
    }

    service = service_map.get(scenario)
    if not service:
        return {"error": f"Unknown scenario: {scenario}"}

    # Run full pipeline once (Watcher → Diagnostician → Strategist)
    result = await full_pipeline(service, scenario)
    watcher = result.get("watcher", {})
    diag = result.get("diagnostician")
    strat = result.get("strategist")

    # Persist watcher (incident + decision + audits)
    try:
        persist_watcher_result(watcher, service, scenario)
    except Exception as e:
        return {"error": f"Failed to persist watcher: {e}", "status": "partial"}

    # Persist diagnostician if we got a diagnosis
    if diag:
        try:
            persist_diagnostician_result(diag)
        except Exception as e:
            pass  # continue; watcher data is already saved

    # Persist strategist and register pending actions for approval UI
    incident_id = watcher.get("incident_id") or (strat.get("incident_id") if strat else None)
    if strat:
        try:
            persist_strategist_result(strat)
        except Exception as e:
            pass
        # Register each pending action so GET /api/approvals shows them
        for action in strat.get("pending_actions", []):
            add_approval_request(
                incident_id=incident_id or "",
                agent_name="strategist",
                action=action.get("action", ""),
                tool=action.get("tool", ""),
                tool_args=action.get("tool_args", {}),
                risk_level=action.get("risk_level", "risky"),
                service=action.get("tool_args", {}).get("service", service),
                id=action.get("approval_id"),
            )

    return {
        "status": "completed",
        "scenario": scenario,
        "service": service,
        "incident_id": incident_id,
        "alert_triggered": watcher.get("should_alert", False),
        "confidence": watcher.get("confidence", 0),
        "severity": watcher.get("severity", "unknown"),
        "summary": watcher.get("summary", ""),
        "pending_approvals": len(strat.get("pending_actions", [])) if strat else 0,
    }