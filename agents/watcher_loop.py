"""
SentinelAI — Watcher Loop

Always-on monitoring loop that replaces manual "Run Scenario" triggering.
Periodically polls Prometheus for anomalies and, when one is confirmed,
runs the full Watcher → Diagnostician → Strategist pipeline and registers
any required approvals.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional, Set

import docker

from backend.prometheus_client import check_anomalies, SERVICES
from backend.database import SessionLocal
from backend.models import Incident

logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.getenv("WATCHER_POLL_INTERVAL", "15"))  # seconds
INITIAL_DELAY = 15  # brief wait for Prometheus to have data after startup
CONSECUTIVE_THRESHOLD = 2  # require N consecutive anomalous checks before alerting
VERIFICATION_CHECKS = 3
HEALTHY_RESOLVE_STREAK = 3  # consecutive healthy polls before auto-resolving

_anomaly_streak: Dict[str, int] = {svc: 0 for svc in SERVICES}
_healthy_streak: Dict[str, int] = {svc: 0 for svc in SERVICES}
_cooldown: Dict[str, int] = {}  # service → remaining cooldown cycles
_pipeline_running: Set[str] = set()
_last_check: Optional[str] = None

DEPENDENCIES: Dict[str, list[str]] = {
    "api-gateway": ["user-service", "payment-service", "redis"],
    "payment-service": ["redis"],
    "user-service": ["redis"],
}


async def _run_full_pipeline_for_service(service: str, anomaly: dict) -> None:
    """
    Run full pipeline (Watcher → Diagnostician → Strategist) for a service,
    then persist results and register approvals. This mirrors the previous
    /api/run-scenario implementation but triggered automatically.
    """
    from agents.strategist import full_pipeline
    from agents.watcher_db import persist_watcher_result
    from agents.diagnostician_db import persist_diagnostician_result
    from agents.strategist_db import persist_strategist_result
    from backend.approval import add_approval_request
    from backend.database import SessionLocal
    from backend.models import Incident, AgentDecision, AuditLog
    from backend.incident_service import (
        mark_investigating_if_open,
        transition_incident_status,
    )

    logger.info("WatcherLoop: starting full pipeline for service=%s", service)

    result = await full_pipeline(service, None, detection_context=anomaly)
    watcher = result.get("watcher", {}) or {}
    diag = result.get("diagnostician")
    strat = result.get("strategist")

    # Persist watcher (incident + decision + audits)
    try:
        persist_watcher_result(watcher, service, None)
    except Exception as e:
        logger.exception("WatcherLoop: failed to persist watcher result: %s", e)
        return

    incident_id_for_log = watcher.get("incident_id") or (strat.get("incident_id") if strat else None)

    # Persist diagnostician if we got a diagnosis
    if diag:
        try:
            persist_diagnostician_result(diag)
        except Exception:
            # continue; watcher data is already saved
            logger.exception("WatcherLoop: failed to persist diagnostician result")

    # Persist strategist and register pending actions for approval UI
    incident_id = watcher.get("incident_id") or (strat.get("incident_id") if strat else None)
    pending_count = 0
    if strat:
        try:
            persist_strategist_result(strat)
        except Exception:
            logger.exception("WatcherLoop: failed to persist strategist result")

        if incident_id:
            pending_count = len(strat.get("pending_actions", []))
            if pending_count == 0:
                # No risky actions — auto-resolve
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

    # Structured log mirroring the old pipeline
    final_status = "N/A"
    if incident_id_for_log:
        db = SessionLocal()
        try:
            inc = db.query(Incident).filter(Incident.id == incident_id_for_log).first()
            final_status = inc.status if inc else "N/A"
        except Exception:
            logger.exception("WatcherLoop: failed to read incident status for log")
        finally:
            db.close()

    logger.info(
        "WatcherLoop pipeline complete: incident_id=%s final_status=%s pending_approvals=%s",
        incident_id_for_log,
        final_status,
        pending_count,
    )


def get_open_incident_for_service(service: str) -> Optional[Incident]:
    """Return the first open/investigating incident for a given service, if any."""
    db = SessionLocal()
    try:
        rows = (
            db.query(Incident)
            .filter(Incident.status.in_(("open", "investigating")))
            .order_by(Incident.detected_at.desc())
            .all()
        )
        for inc in rows:
            meta = inc.metadata_ or {}
            if str(meta.get("service")) == service:
                return inc
    finally:
        db.close()
    return None


async def verify_remediation(service: str, incident_id: str) -> bool:
    """
    Monitor a service after remediation. If it is healthy for VERIFICATION_CHECKS
    consecutive polls, log success and, if the service was scaled up, scale back to 1.
    """
    healthy_count = 0
    for _ in range(VERIFICATION_CHECKS * 2):
        await asyncio.sleep(POLL_INTERVAL)
        anomaly = await check_anomalies(service)
        if anomaly is None:
            healthy_count += 1
            if healthy_count >= VERIFICATION_CHECKS:
                # If service was scaled up during remediation, scale back to 1
                try:
                    client = docker.from_env()
                    containers = client.containers.list(filters={"name": f"sentinel-{service}"})
                    if len(containers) > 1:
                        logger.info("Scaling %s back to 1 replica after verified remediation", service)
                        import subprocess

                        subprocess.run(
                            ["docker-compose", "up", "-d", "--scale", f"{service}=1"],
                            check=False,
                        )
                except Exception:
                    logger.exception("Failed to scale %s back to 1 replica", service)

                logger.info("Remediation verified for %s incident=%s", service, incident_id)
                return True
        else:
            healthy_count = 0

    logger.warning("%s still anomalous after remediation for incident %s", service, incident_id)
    return False


async def watcher_loop() -> None:
    """
    Always-on loop that checks each service for anomalies and triggers
    the full agent pipeline when anomalies persist.
    """
    global _last_check

    logger.info(
        "WatcherLoop starting with POLL_INTERVAL=%ss, services=%s",
        POLL_INTERVAL,
        ", ".join(SERVICES),
    )

    # Initial delay to let Prometheus and services warm up
    await asyncio.sleep(INITIAL_DELAY)

    while True:
        # Update shared last_check so /api/watcher/status can report recent activity
        _last_check = datetime.now(timezone.utc).isoformat()

        for service in SERVICES:
            # Fix 6: post-pipeline cooldown — skip 1 cycle after completion
            if _cooldown.get(service, 0) > 0:
                _cooldown[service] -= 1
                continue

            try:
                anomaly = await check_anomalies(service)
            except Exception as e:
                logger.exception("WatcherLoop: check_anomalies failed for %s: %s", service, e)
                _anomaly_streak[service] = 0
                continue

            if anomaly is None:
                _anomaly_streak[service] = 0
                _healthy_streak[service] = _healthy_streak.get(service, 0) + 1

                # Fix 2: auto-resolve when healthy for N consecutive polls
                if _healthy_streak[service] >= HEALTHY_RESOLVE_STREAK:
                    try:
                        open_inc = get_open_incident_for_service(service)
                        if open_inc:
                            from backend.incident_service import transition_incident_status
                            resolved = transition_incident_status(open_inc.id, "resolved")
                            if resolved:
                                logger.info("[WATCHER_LOOP] Auto-resolved incident %s for service=%s (healthy for %d polls)", open_inc.id[:12], service, _healthy_streak[service])
                    except Exception as e:
                        logger.warning("[WATCHER_LOOP] auto-resolve DB check failed for %s: %s", service, e)
                continue

            # Anomaly detected — reset healthy streak
            _healthy_streak[service] = 0
            _anomaly_streak[service] = _anomaly_streak.get(service, 0) + 1
            logger.info(
                "WatcherLoop: anomaly on %s, streak=%s, worst_severity=%s",
                service,
                _anomaly_streak[service],
                anomaly.get("worst_severity"),
            )

            # Cascading failure deduplication
            try:
                if service in DEPENDENCIES:
                    upstream_with_incidents = [
                        dep for dep in DEPENDENCIES[service] if get_open_incident_for_service(dep)
                    ]
                    if upstream_with_incidents:
                        logger.info(
                            "WatcherLoop: skipping %s — upstream %s has open incident(s) (cascading failure)",
                            service,
                            upstream_with_incidents,
                        )
                        _anomaly_streak[service] = 0
                        continue

                # Fix 1: dedup — skip if open incident already exists for this service
                if get_open_incident_for_service(service):
                    continue
            except Exception as e:
                logger.warning("[WATCHER_LOOP] DB dedup check failed for %s: %s", service, e)
                continue

            if (
                _anomaly_streak[service] >= CONSECUTIVE_THRESHOLD
                and service not in _pipeline_running
            ):
                logger.info("[WATCHER_LOOP] TRIGGERING PIPELINE for service=%s streak=%d", service, _anomaly_streak[service])
                _pipeline_running.add(service)

                async def _runner(svc: str, a: dict) -> None:
                    try:
                        await _run_full_pipeline_for_service(svc, a)
                        logger.info("[WATCHER_LOOP] Pipeline completed for service=%s", svc)
                    except Exception as exc:
                        logger.error("[WATCHER_LOOP] Pipeline FAILED for service=%s error=%s", svc, exc)
                    finally:
                        _pipeline_running.discard(svc)
                        _anomaly_streak[svc] = 0
                        _cooldown[svc] = 1  # Fix 6: skip next poll cycle

                asyncio.create_task(_runner(service, anomaly))
            elif service in _pipeline_running:
                pass

        # Multi-service anomaly detection for cache_failure (Redis)
        anomalous_services = [s for s in SERVICES if _anomaly_streak.get(s, 0) >= 1]
        if len(anomalous_services) >= 2:
            redis_status = "unknown"
            try:
                client = docker.from_env()
                redis_container = client.containers.get("sentinel-redis")
                redis_status = redis_container.status
            except Exception:
                pass

            # Fix 8: also check _pipeline_running to prevent duplicate Redis pipelines
            if redis_status != "running" and "redis" not in _pipeline_running:
                if not get_open_incident_for_service("redis"):
                    logger.info(
                        "WatcherLoop: Multi-service degradation detected. Redis is down. Triggering cache_failure pipeline."
                    )
                    _pipeline_running.add("redis")

                    async def _runner_cache(affected: list[str]) -> None:
                        try:
                            await _run_full_pipeline_for_service(
                                "redis",
                                {
                                    "service": "redis",
                                    "anomalies": [
                                        {
                                            "metric": "up",
                                            "value": 0,
                                            "threshold": 1,
                                            "severity": "critical",
                                        }
                                    ],
                                    "worst_severity": "critical",
                                    "detection_metrics": {
                                        "status": "down",
                                        "affected_services": affected,
                                    },
                                },
                            )
                        finally:
                            _pipeline_running.discard("redis")
                            for s in affected:
                                _anomaly_streak[s] = 0

                    asyncio.create_task(_runner_cache(anomalous_services))

        await asyncio.sleep(POLL_INTERVAL)


__all__ = [
    "watcher_loop",
    "POLL_INTERVAL",
    "INITIAL_DELAY",
    "_anomaly_streak",
    "_healthy_streak",
    "_cooldown",
    "_last_check",
    "SERVICES",
]

