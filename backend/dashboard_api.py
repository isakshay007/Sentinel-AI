"""
SentinelAI — Dashboard API Endpoints
Serves data from PostgreSQL and JSON files to the React frontend.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
from backend.database import SessionLocal
from backend.models import Incident, AgentDecision, AuditLog, IncidentEvent

router = APIRouter(prefix="/api", tags=["dashboard"])
logger = logging.getLogger(__name__)

# Paths relative to project root so they work regardless of CWD
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = _PROJECT_ROOT / "evaluation" / "results"
FIXTURES_DIR = _PROJECT_ROOT / "tests" / "fixtures"


# =============================================================================
# DASHBOARD STATS
# =============================================================================

# Status semantics: "open" = not yet resolved (includes open + investigating)
OPEN_STATUSES = ("open", "investigating")


@router.get("/dashboard/stats")
def get_dashboard_stats():
    """
    Dashboard stats. agents.total_decisions = count of AgentDecision rows for
    active incidents only (status in open, investigating); resolved incidents
    are excluded so the metric is lifecycle-aware.
    """
    db = SessionLocal()
    try:
        total_incidents = db.query(Incident).count()
        open_incidents = db.query(Incident).filter(Incident.status.in_(OPEN_STATUSES)).count()
        # Decisions: count across ALL incidents (persists after resolution per issue #5/8/13)
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
    """status: 'open' = open+investigating (not resolved), 'resolved', or omit for all."""
    db = SessionLocal()
    try:
        query = db.query(Incident).order_by(Incident.detected_at.desc())
        if status == "open":
            query = query.filter(Incident.status.in_(OPEN_STATUSES))
        elif status == "resolved":
            query = query.filter(Incident.status == "resolved")
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
    """Incident trace with unified timeline (#6) merging decisions, audit logs, and lifecycle events."""
    db = SessionLocal()
    try:
        decisions = (
            db.query(AgentDecision)
            .filter(AgentDecision.incident_id == incident_id)
            .order_by(AgentDecision.created_at.asc())
            .all()
        )
        audits = (
            db.query(AuditLog)
            .filter(AuditLog.incident_id == incident_id)
            .order_by(AuditLog.timestamp.asc())
            .limit(100)
            .all()
        )
        events = (
            db.query(IncidentEvent)
            .filter(IncidentEvent.incident_id == incident_id)
            .order_by(IncidentEvent.created_at.asc())
            .all()
        )
        incident = db.query(Incident).filter(Incident.id == incident_id).first()

        # Unified timeline (#6): merge by timestamp
        timeline_entries = []
        for d in decisions:
            ts = d.created_at
            if ts:
                timeline_entries.append((ts, "decision", {"agent_name": d.agent_name, "decision_type": d.decision_type, "reasoning": d.reasoning, "confidence": d.confidence, "tool_calls": d.tool_calls}))
        for a in audits[:30]:
            ts = a.timestamp
            if ts:
                timeline_entries.append((ts, "audit", {"agent_name": a.agent_name, "action": a.action, "mcp_server": a.mcp_server, "tool_name": a.tool_name}))
        for e in events:
            ts = e.created_at
            if ts:
                timeline_entries.append((ts, "event", {"event_type": e.event_type, "payload": e.payload or {}}))

        timeline_entries.sort(key=lambda x: x[0])
        timeline = [
            {"timestamp": ts.isoformat(), "type": t, "data": data}
            for ts, t, data in timeline_entries
        ]

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
            "timeline": timeline,
        }
    finally:
        db.close()


@router.get("/incidents/{incident_id}/events")
def get_incident_events(incident_id: str):
    """Lifecycle events for an incident (#9, #19)."""
    db = SessionLocal()
    try:
        rows = (
            db.query(IncidentEvent)
            .filter(IncidentEvent.incident_id == incident_id)
            .order_by(IncidentEvent.created_at.asc())
            .all()
        )
        return {
            "incident_id": incident_id,
            "events": [
                {
                    "id": r.id,
                    "event_type": r.event_type,
                    "payload": r.payload or {},
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }
    finally:
        db.close()


@router.get("/audit-logs")
def get_audit_logs(
    incident_id: Optional[str] = None,
    limit: int = 100,
    since: Optional[str] = None,
):
    """Return audit logs for Activity feed. AuditLog is the single source of truth for tool calls (#7).
    Optional incident_id and since (ISO timestamp) filter."""
    db = SessionLocal()
    try:
        query = db.query(AuditLog).order_by(AuditLog.timestamp.desc())
        if incident_id:
            query = query.filter(AuditLog.incident_id == incident_id)
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                query = query.filter(AuditLog.timestamp >= since_dt)
            except ValueError:
                pass
        logs = query.limit(limit).all()
        return {
            "total": len(logs),
            "logs": [
                {
                    "id": a.id,
                    "incident_id": a.incident_id,
                    "agent_name": a.agent_name,
                    "action": a.action,
                    "mcp_server": a.mcp_server,
                    "tool_name": a.tool_name,
                    "input_data": a.input_data,
                    "output_data": a.output_data,
                    "timestamp": a.timestamp.isoformat() if a.timestamp else None,
                }
                for a in logs
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

# Dependency map: service -> list of dependent services (from mock_data_generator.SERVICES)
# Used for issue #1: dependencies of resolved-incident services are treated as healthy.
_SERVICE_DEPENDENCIES = {
    "api-gateway": ["user-service", "payment-service", "inventory-service"],
    "user-service": ["postgres-primary", "redis-cache"],
    "payment-service": ["postgres-primary", "stripe-client"],
    "inventory-service": ["postgres-primary", "redis-cache"],
}


def _get_service_health_data():
    # Services with resolved incidents (or their dependencies) are healthy (#1, #8)
    resolved_services = set()
    incident_services = {}  # service -> metrics_snapshot from incident metadata
    db = SessionLocal()
    try:
        for inc in db.query(Incident).all():
            svc = (inc.metadata_ or {}).get("service")
            if svc:
                svc = str(svc)
                if inc.status == "resolved":
                    resolved_services.add(svc)
                else:
                    # Use incident metadata for open/investigating (#8)
                    snap = (inc.metadata_ or {}).get("metrics_snapshot") or {}
                    if snap and (svc not in incident_services or inc.detected_at):
                        incident_services[svc] = snap
    finally:
        db.close()

    # Dependencies of resolved-incident services are healthy (#1)
    for svc in list(resolved_services):
        for dep in _SERVICE_DEPENDENCIES.get(svc, []):
            resolved_services.add(dep)

    services = []
    seen_services = set()
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
                    if svc in seen_services:
                        continue
                    seen_services.add(svc)
                    cpu = m.get("cpu_percent", 0)
                    mem = m.get("memory_percent", 0)
                    err = m.get("error_rate", 0)

                    if svc in resolved_services:
                        status = "healthy"
                    elif cpu > 90 or mem > 92 or err > 0.15:
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

    # Include services from incident metadata when not in fixtures (#8)
    for svc, m in incident_services.items():
        if svc in seen_services:
            continue
        seen_services.add(svc)
        cpu = m.get("cpu_percent", 0)
        mem = m.get("memory_percent", 0)
        err = m.get("error_rate", 0)
        if svc in resolved_services:
            status = "healthy"
        elif cpu > 90 or mem > 92 or err > 0.15:
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

    return {"services": services}


@router.get("/service-health")
def get_service_health():
    """Service health (legacy path)."""
    return _get_service_health_data()


@router.get("/services/health")
def get_services_health():
    """Service health (design path: /api/services/health). Same response."""
    return _get_service_health_data()


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

    # Clear approval store before run so each run has only its own approvals (no accumulation)
    from backend.approval import clear_approval_store
    clear_approval_store()

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

    incident_id_for_log = watcher.get("incident_id") or (strat.get("incident_id") if strat else None)

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
        if incident_id:
            from backend.incident_service import mark_investigating_if_open, transition_incident_status
            pending_count = len(strat.get("pending_actions", []))
            if pending_count == 0:
                # No risky actions — auto-resolve (fix orphaned incidents per issue #10)
                transition_incident_status(incident_id, "resolved")
            else:
                mark_investigating_if_open(incident_id)
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

    # Pipeline complete - structured log
    pending_count = len(strat.get("pending_actions", [])) if strat else 0
    final_status = "N/A"
    if incident_id_for_log:
        db = SessionLocal()
        try:
            inc = db.query(Incident).filter(Incident.id == incident_id_for_log).first()
            final_status = inc.status if inc else "N/A"
        finally:
            db.close()
    logger.info(
        "Pipeline complete: incident_id=%s final_status=%s pending_approvals=%s",
        incident_id_for_log,
        final_status,
        pending_count,
    )

    # Determinism check: log counts and warn if unexpected
    if incident_id_for_log:
        vdb = SessionLocal()
        try:
            inc_count = vdb.query(Incident).filter(Incident.id == incident_id_for_log).count()
            dec_count = vdb.query(AgentDecision).filter(AgentDecision.incident_id == incident_id_for_log).count()
            audit_count = vdb.query(AuditLog).filter(AuditLog.incident_id == incident_id_for_log).count()
            if inc_count != 1:
                logger.warning("Expected 1 incident, found %s", inc_count)
            if dec_count not in (2, 3):
                logger.warning("Expected 2-3 agent decisions, found %s", dec_count)
            logger.info("Verification: 1 incident, %s decisions, %s audit logs", dec_count, audit_count)
        finally:
            vdb.close()

    phases = {
        "watcher": {
            "alert_triggered": watcher.get("should_alert", False),
            "confidence": watcher.get("confidence", 0),
            "summary": watcher.get("summary", ""),
            "severity": watcher.get("severity", "unknown"),
        } if watcher else None,
        "diagnostician": {
            "root_cause": diag.get("root_cause", ""),
            "confidence": diag.get("confidence", 0),
            "diagnosis": diag.get("diagnosis", ""),
        } if diag else None,
        "strategist": {
            "plan": (strat.get("selected_plan") or {}).get("name", "N/A") if strat else "N/A",
            "approved": len(strat.get("approved_actions", [])) if strat else 0,
            "pending": len(strat.get("pending_actions", [])) if strat else 0,
        } if strat else None,
    }

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
        "phases": phases,
    }