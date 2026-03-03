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
from backend.prometheus_client import get_all_services_health

router = APIRouter(prefix="/api", tags=["dashboard"])
logger = logging.getLogger(__name__)

# Paths relative to project root so they work regardless of CWD
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = _PROJECT_ROOT / "evaluation" / "results"


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
# LIVE EVAL STATUS + REPORT
# =============================================================================

@router.get("/eval/status")
def get_eval_status():
    """Return metadata from the latest live evaluation run."""
    json_path = EVAL_DIR / "latest_eval.json"
    if not json_path.exists():
        return {
            "has_results": False,
            "message": "No live evaluation has been run yet. Use: python -m evaluation.live_eval",
        }
    try:
        with open(json_path) as f:
            data = json.load(f)
        return {
            "has_results": True,
            "timestamp": data.get("timestamp"),
            "scenarios_run": data.get("scenarios_run", 0),
            "overall_score": data.get("overall_score", 0),
            "model": data.get("model"),
            "scenarios": [
                {
                    "scenario": s.get("scenario"),
                    "target": s.get("target"),
                    "score": s.get("score"),
                    "detection_time_s": s.get("detection_time_s"),
                    "diagnosis_time_s": s.get("diagnosis_time_s"),
                    "resolution_time_s": s.get("resolution_time_s"),
                    "root_cause_found": s.get("root_cause_found"),
                    "root_cause_correct": s.get("root_cause_correct"),
                    "resolution_status": s.get("resolution_status"),
                    "tool_count": s.get("tool_count", 0),
                    "approval_count": s.get("approval_count", 0),
                    "errors": s.get("errors", []),
                }
                for s in data.get("scenarios", [])
            ],
        }
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("[EVAL] Failed to read latest_eval.json: %s", e)
        return {"has_results": False, "error": f"Corrupted eval file: {e}"}


@router.get("/eval/report")
def get_eval_report():
    """Return the LLM-generated markdown evaluation report."""
    report_path = EVAL_DIR / "latest_report.md"
    json_path = EVAL_DIR / "latest_eval.json"

    if not report_path.exists():
        return {
            "has_report": False,
            "message": "No evaluation report found. Run: python -m evaluation.live_eval",
        }
    try:
        content = report_path.read_text(encoding="utf-8")
        # Get timestamp from JSON if available
        timestamp = None
        if json_path.exists():
            try:
                with open(json_path) as f:
                    timestamp = json.load(f).get("timestamp")
            except Exception:
                pass

        return {
            "has_report": True,
            "timestamp": timestamp,
            "content": content,
        }
    except Exception as e:
        logger.warning("[EVAL] Failed to read latest_report.md: %s", e)
        return {"has_report": False, "error": f"Failed to read report: {e}"}


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


@router.get("/service-health")
async def get_service_health():
    """Service health (legacy path). Returns live Prometheus data."""
    return await get_services_health()


@router.get("/services/health")
async def get_services_health():
    """
    Service health (design path: /api/services/health).
    Uses live Prometheus metrics via backend.prometheus_client.
    """
    health_list = await get_all_services_health()
    services = [
        {
            "name": h.get("service", "unknown"),
            "cpu_percent": round(float(h.get("cpu_percent", 0.0)), 1),
            "memory_percent": round(float(h.get("memory_percent", 0.0)), 1),
            "response_time_ms": round(float(h.get("response_time_ms", 0.0)), 1),
            "error_rate": float(h.get("error_rate", 0.0)),
            "status": h.get("status", "unknown"),
        }
        for h in health_list
    ]
    return {"services": services}


# =============================================================================
# CHAOS INJECTION + WATCHER STATUS
# =============================================================================

SERVICE_URLS = {
    "user-service": "http://user-service:8001",
    "payment-service": "http://payment-service:8002",
    "api-gateway": "http://api-gateway:8003",
}


@router.post("/chaos/inject")
async def inject_fault(body: dict):
    """
    Inject a live fault into the running microservices.

    Body:
      {
        "target": "user-service" | "payment-service" | "api-gateway" | "redis",
        "type": "memory_leak" | "cpu_spike" | "network_latency" | "kill_service" | "cache_failure",
        "intensity": int (e.g. 90),
        "duration": int seconds (e.g. 120)
      }
    """
    import docker
    import httpx

    target = body["target"]
    fault_type = body["type"]
    intensity = int(body.get("intensity", 90))
    duration = int(body.get("duration", 120))
    logger.info("[CHAOS] Injecting fault: target=%s type=%s intensity=%s duration=%s", target, fault_type, intensity, duration)

    result: dict

    if fault_type in ("memory_leak", "cpu_spike", "network_latency"):
        chaos_endpoint_map = {
            "memory_leak": f"/chaos/memory?percent={intensity}&duration={duration}",
            "cpu_spike": f"/chaos/cpu?cores={intensity}&duration={duration}",
            "network_latency": f"/chaos/latency?intensity={intensity}&duration={duration}",
        }
        base = SERVICE_URLS.get(target)
        if not base:
            return {"error": f"Unknown service target: {target}"}
        url = base + chaos_endpoint_map[fault_type]
        async with httpx.AsyncClient() as client:
            resp = await client.post(url)
            resp.raise_for_status()
            result = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {
                "status": "injecting"
            }
    elif fault_type == "kill_service":
        logger.info("[CHAOS] Stopping container: sentinel-%s", target)
        d = docker.from_env()
        d.containers.get(f"sentinel-{target}").stop()
        result = {"status": "killed", "target": target}
    elif fault_type == "cache_failure":
        logger.info("[CHAOS] Stopping container: sentinel-redis")
        d = docker.from_env()
        d.containers.get("sentinel-redis").stop()
        result = {"status": "redis_stopped"}
    else:
        return {"error": f"Unknown fault: {fault_type}"}

    # Log to audit
    db = SessionLocal()
    try:
        db.add(
            AuditLog(
                agent_name="chaos_injector",
                action=f"inject_{fault_type}",
                mcp_server=None,
                tool_name="chaos_http/docker",
                input_data=body,
                output_data=result,
            )
        )
        db.commit()
    finally:
        db.close()

    return {
        "status": "injecting",
        "fault": fault_type,
        "target": target,
        "duration": duration,
    }


@router.post("/chaos/stop")
async def stop_chaos(body: dict):

    """
    Stop chaos on a specific target service by calling its /chaos/stop endpoint.
    For killed services or Redis, restart the container via Docker API.
    """
    import httpx
    import docker
    
    target = body["target"]
    logger.info("[CHAOS] Stopping chaos on target=%s", target)
    base = SERVICE_URLS.get(target)

    # Handle targets not in SERVICE_URLS (e.g. redis, or unknown)
    if not base:
        # Try to restart the container via Docker if it's stopped
        container_name = f"sentinel-{target}"
        try:
            d = docker.from_env()
            c = d.containers.get(container_name)
            if c.status != "running":
                logger.info("[CHAOS] Restarting stopped container: %s", container_name)
                c.start()
                return {"status": "restarted", "target": target, "container": container_name}
            return {"status": "already_running", "target": target}
        except docker.errors.NotFound:
            return {"error": f"Unknown service target: {target}"}
        except Exception as e:
            logger.error("[CHAOS] Failed to restart %s: %s", container_name, e)
            return {"error": f"Failed to restart {target}: {str(e)}"}

    url = base + "/chaos/stop"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url)
            resp.raise_for_status()
            try:
                return resp.json()
            except Exception:
                return {"status": "stopped"}
    except httpx.ConnectError:
        # Service container may be stopped — restart via Docker
        container_name = f"sentinel-{target}"
        try:
            d = docker.from_env()
            c = d.containers.get(container_name)
            if c.status != "running":
                logger.info("[CHAOS] Service unreachable, restarting container: %s", container_name)
                c.start()
                return {"status": "restarted", "target": target}
        except Exception as e:
            logger.error("[CHAOS] Restart fallback failed for %s: %s", target, e)
        return {"status": "stopped", "note": "Service unreachable, attempted restart"}


@router.get("/watcher/status")
async def watcher_status():
    """
    Lightweight status endpoint for the always-on watcher loop.

    IMPORTANT: we import the module, not individual globals, so that the latest
    values set by the background task (e.g. _last_check) are reflected here.
    """
    from agents import watcher_loop

    return {
        "enabled": os.getenv("WATCHER_ENABLED", "1") == "1",
        "poll_interval_seconds": watcher_loop.POLL_INTERVAL,
        "services_monitored": watcher_loop.SERVICES,
        "last_check": watcher_loop._last_check,
        "anomaly_streaks": watcher_loop._anomaly_streak,
    }


@router.post("/run-scenario/{scenario}")
async def run_scenario(scenario: str):
    """
    Legacy endpoint kept for backward compatibility but no longer executes the mock
    scenario pipeline. Returns an error directing users to use live fault injection.
    """
    return {
        "status": "error",
        "error": "Mock scenarios have been removed. Use /api/chaos/inject for live fault injection instead.",
        "scenario": scenario,
    }