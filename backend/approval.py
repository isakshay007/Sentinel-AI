"""
SentinelAI — Human-in-the-Loop Approval API
FastAPI endpoints for approving/rejecting risky and dangerous actions.
Approving triggers Executor to run the action, persist audit logs, and update incident status.
Approvals persisted in PostgreSQL (#5, #11).
"""

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

from backend.database import SessionLocal
from backend.models import Approval as ApprovalModel

router = APIRouter(prefix="/api", tags=["approvals"])
logger = logging.getLogger(__name__)

# Concurrency control (#13): per-action_id lock
_approval_locks: dict[str, threading.Lock] = {}
_lock_factory = threading.Lock()


def _get_action_lock(action_id: str) -> threading.Lock:
    with _lock_factory:
        if action_id not in _approval_locks:
            _approval_locks[action_id] = threading.Lock()
        return _approval_locks[action_id]


class ApprovalRequest(BaseModel):
    id: str
    incident_id: Optional[str] = None
    agent_name: str
    action: str
    tool: str
    tool_args: dict
    risk_level: str
    service: str
    status: str = "pending"
    requested_at: str
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    reason: Optional[str] = None


class ApprovalDecision(BaseModel):
    decided_by: str = "human_operator"
    reason: Optional[str] = None


def _row_to_request(row) -> ApprovalRequest:
    return ApprovalRequest(
        id=row.id,
        incident_id=row.incident_id,
        agent_name=row.agent_name,
        action=row.action,
        tool=row.tool,
        tool_args=row.tool_args or {},
        risk_level=row.risk_level or "risky",
        service=row.service or "",
        status=row.status or "pending",
        requested_at=row.requested_at.isoformat() if row.requested_at else "",
        decided_at=row.decided_at.isoformat() if row.decided_at else None,
        decided_by=row.decided_by,
        reason=row.reason,
    )


def add_approval_request(
    incident_id: str,
    agent_name: str,
    action: str,
    tool: str,
    tool_args: dict,
    risk_level: str,
    service: str,
    id: Optional[str] = None,
) -> ApprovalRequest:
    """Add approval request to DB. Called by Strategist or pipeline API."""
    approval_id = id or str(uuid.uuid4())
    logger.info("[APPROVAL] Created approval request: id=%s tool=%s service=%s incident_id=%s", approval_id[:12], tool, service, incident_id[:8] if incident_id else "N/A")
    db = SessionLocal()
    try:
        existing = db.query(ApprovalModel).filter(ApprovalModel.id == approval_id).first()
        if existing:
            logger.warning("Duplicate approval_id %s - skipping (idempotent)", approval_id[:12])
            return _row_to_request(existing)
        row = ApprovalModel(
            id=approval_id,
            incident_id=incident_id or None,
            agent_name=agent_name,
            action=action,
            tool=tool,
            tool_args=tool_args,
            risk_level=risk_level,
            service=service,
            status="pending",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info("Approval created: %s (incident=%s)", action[:50], (incident_id or "N/A")[:8])
        return _row_to_request(row)
    finally:
        db.close()


def get_pending() -> List[ApprovalRequest]:
    db = SessionLocal()
    try:
        rows = db.query(ApprovalModel).filter(ApprovalModel.status == "pending").all()
        return [_row_to_request(r) for r in rows]
    finally:
        db.close()


def clear_approval_store(all_: bool = False) -> None:
    """Clear approvals. all_=False: pending only (run-scenario). all_=True: all (dev reset)."""
    db = SessionLocal()
    try:
        if all_:
            db.query(ApprovalModel).delete()
        else:
            db.query(ApprovalModel).filter(ApprovalModel.status == "pending").delete()
        db.commit()
    finally:
        db.close()


def get_all() -> List[ApprovalRequest]:
    db = SessionLocal()
    try:
        rows = db.query(ApprovalModel).order_by(ApprovalModel.requested_at.desc()).all()
        return [_row_to_request(r) for r in rows]
    finally:
        db.close()


def get_by_id(action_id: str) -> Optional[ApprovalRequest]:
    db = SessionLocal()
    try:
        row = db.query(ApprovalModel).filter(ApprovalModel.id == action_id).first()
        return _row_to_request(row) if row else None
    finally:
        db.close()


def update_approval_status(
    action_id: str, status: str, decided_by: str, reason: Optional[str] = None
) -> bool:
    db = SessionLocal()
    try:
        row = db.query(ApprovalModel).filter(ApprovalModel.id == action_id).first()
        if not row:
            return False
        row.status = status
        row.decided_at = datetime.now(timezone.utc)
        row.decided_by = decided_by
        row.reason = reason
        db.commit()
        return True
    finally:
        db.close()


# =============================================================================
# API ENDPOINTS
# =============================================================================

@router.get("/approvals")
def list_pending_approvals():
    """List all pending approval requests. Explicitly filters by status=pending."""
    pending = [r for r in get_pending() if r.status == "pending"]
    return {
        "total_pending": len(pending),
        "approvals": [r.model_dump() for r in pending],
    }


@router.post("/approve/{action_id}")
def approve_action(action_id: str, decision: Optional[ApprovalDecision] = Body(default=None)):
    """Approve a pending action. Triggers Executor, persists audit logs, updates incident status.
    Concurrency control (#13): per-action lock prevents double approval."""
    logger.info("[APPROVAL] Approving action: id=%s", action_id)
    req = get_by_id(action_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"Approval {action_id} not found")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail=f"Action already {req.status}")

    lock = _get_action_lock(action_id)
    with lock:
        req = get_by_id(action_id)
        if not req or req.status != "pending":
            raise HTTPException(status_code=400, detail=f"Action already {req.status if req else 'not found'}")

        from agents.executor_crew import execute_single_tool
        from backend.models import AgentDecision, AuditLog, Incident
        from backend.database import SessionLocal
        from backend.incident_service import (
            is_last_pending_for_incident,
            transition_incident_status,
            emit_incident_event,
        )

        incident_id = req.incident_id or ""

        # Fix 11: reject execution if incident is already resolved
        if incident_id:
            db_check = SessionLocal()
            try:
                inc = db_check.query(Incident).filter(Incident.id == incident_id).first()
                if inc and inc.status == "resolved":
                    update_approval_status(action_id, "cancelled", "system", "Incident already resolved")
                    return {
                        "status": "cancelled",
                        "action_id": action_id,
                        "message": "Incident already resolved — action not executed",
                        "incident_id": incident_id,
                    }
            finally:
                db_check.close()
        logger.info("[APPROVAL] Approving action: id=%s tool=%s", action_id[:12], req.tool)

        # Check BEFORE changing status
        will_resolve = (
            incident_id and
            is_last_pending_for_incident(incident_id, action_id)
        )

        decided_by = decision.decided_by if decision else "human_operator"
        reason_val = decision.reason if decision else None

        # Persist status to DB
        update_approval_status(action_id, "approved", decided_by, reason_val)

    # Execute outside lock (potentially slow)
    execution_result = None
    incident_resolved = False

    try:
        exec_out = execute_single_tool(req.tool, req.tool_args)
        execution_result = exec_out

        result_summary = str(exec_out)[:200]

        # Persist audit log
        db = SessionLocal()
        try:
            mcp_server = (
                "alert_server"
                if req.tool in ("send_notification", "create_incident_ticket")
                else "infra_server"
            )

            audit = AuditLog(
                incident_id=incident_id or None,
                agent_name="executor",
                action="mcp_tool_call",
                mcp_server=mcp_server,
                tool_name=req.tool,
                input_data=req.tool_args,
                output_data={"summary": result_summary},
                timestamp=datetime.now(timezone.utc),
            )
            db.add(audit)

            # Persist executor as AgentDecision so Agent terminal shows it (#2)
            tool_calls_list = [{"tool": req.tool, "args": req.tool_args, "result_summary": result_summary}]
            exec_decision = AgentDecision(
                incident_id=incident_id or None,
                agent_name="executor",
                decision_type="execute",
                reasoning=json.dumps({
                    "action": req.action,
                    "tool": req.tool,
                    "status": exec_out.get("status", "unknown"),
                    "decided_by": decided_by,
                }),
                confidence=1.0 if exec_out.get("status") == "completed" else 0.0,
                tool_calls=tool_calls_list,
                created_at=datetime.now(timezone.utc),
            )
            db.add(exec_decision)

            db.commit()
        finally:
            db.close()

        # Resolve incident only if:
        # - This was the last pending approval
        # - Tool execution succeeded
        if (
            will_resolve
            and incident_id
            and exec_out.get("status") == "completed"
        ):
            incident_resolved = transition_incident_status(
                incident_id,
                "resolved"
            )
        emit_incident_event(incident_id or None, "approval", {"action_id": action_id, "status": "approved", "tool": req.tool})

        logger.info("[APPROVAL] Execution result: tool=%s success=%s", req.tool, exec_out.get("status", "unknown"))
        if will_resolve and incident_id and exec_out.get("status") == "completed":
            logger.info("[APPROVAL] All approvals done for incident=%s, marking resolved", incident_id[:12])

    except Exception as e:
        execution_result = {"error": str(e), "status": "failed"}
        logger.exception("[APPROVAL] Execution failed: %s", e)

    return {
        "status": "approved",
        "action_id": action_id,
        "action": req.action,
        "tool": req.tool,
        "risk_level": req.risk_level,
        "decided_by": decided_by,
        "message": (
            "Action approved and executed."
            if execution_result
            else "Action approved. Execution failed."
        ),
        "execution_result": execution_result,
        "incident_resolved": incident_resolved,
        "incident_id": incident_id,
    }

@router.post("/reject/{action_id}")
def reject_action(action_id: str, decision: Optional[ApprovalDecision] = Body(default=None)):
    """Reject a pending action. Concurrency control (#13): per-action lock."""
    req = get_by_id(action_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"Approval {action_id} not found")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail=f"Action already {req.status}")

    lock = _get_action_lock(action_id)
    with lock:
        req = get_by_id(action_id)
        if not req or req.status != "pending":
            raise HTTPException(status_code=400, detail=f"Action already {req.status if req else 'not found'}")

        decided_by = decision.decided_by if decision else "human_operator"
        reason_val = decision.reason if decision else "Rejected by operator"
        update_approval_status(action_id, "rejected", decided_by, reason_val)

        try:
            from backend.incident_service import emit_incident_event
            emit_incident_event(req.incident_id, "approval", {"action_id": action_id, "status": "rejected", "reason": reason_val})
        except Exception:
            pass

    return {
        "status": "rejected",
        "action_id": action_id,
        "action": req.action,
        "reason": reason_val,
    }


@router.get("/approvals/history")
def approval_history():
    """Get all approval requests with their decisions."""
    all_requests = get_all()
    return {
        "total": len(all_requests),
        "pending": len([r for r in all_requests if r.status == "pending"]),
        "approved": len([r for r in all_requests if r.status == "approved"]),
        "rejected": len([r for r in all_requests if r.status == "rejected"]),
        "history": [r.model_dump() for r in all_requests],
    }