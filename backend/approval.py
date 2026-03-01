"""
SentinelAI — Human-in-the-Loop Approval API
FastAPI endpoints for approving/rejecting risky and dangerous actions.

Endpoints:
  GET  /api/approvals          — List pending approvals
  POST /api/approve/{action_id} — Approve an action
  POST /api/reject/{action_id}  — Reject an action
  GET  /api/approvals/history  — Approval history
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Optional, List
import uuid

router = APIRouter(prefix="/api", tags=["approvals"])


# =============================================================================
# IN-MEMORY APPROVAL STORE
# =============================================================================

class ApprovalRequest(BaseModel):
    id: str
    incident_id: Optional[str] = None
    agent_name: str
    action: str
    tool: str
    tool_args: dict
    risk_level: str
    service: str
    status: str = "pending"  # pending, approved, rejected
    requested_at: str
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    reason: Optional[str] = None


class ApprovalDecision(BaseModel):
    decided_by: str = "human_operator"
    reason: Optional[str] = None


# In-memory store (in production this would be in PostgreSQL)
_approval_store: dict[str, ApprovalRequest] = {}


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
    """Add a new approval request. Called by the Strategist or pipeline API.
    Pass id=approval_id to use the Strategist's approval_id so frontend approve/reject matches."""
    req = ApprovalRequest(
        id=id or str(uuid.uuid4()),
        incident_id=incident_id,
        agent_name=agent_name,
        action=action,
        tool=tool,
        tool_args=tool_args,
        risk_level=risk_level,
        service=service,
        requested_at=datetime.now(timezone.utc).isoformat(),
    )
    _approval_store[req.id] = req
    return req


def get_pending() -> List[ApprovalRequest]:
    return [r for r in _approval_store.values() if r.status == "pending"]


def get_all() -> List[ApprovalRequest]:
    return list(_approval_store.values())


# =============================================================================
# API ENDPOINTS
# =============================================================================

@router.get("/approvals")
def list_pending_approvals():
    """List all pending approval requests."""
    pending = get_pending()
    return {
        "total_pending": len(pending),
        "approvals": [r.model_dump() for r in pending],
    }


@router.post("/approve/{action_id}")
def approve_action(action_id: str, decision: ApprovalDecision = None):
    """Approve a pending action for execution."""
    if action_id not in _approval_store:
        raise HTTPException(status_code=404, detail=f"Approval {action_id} not found")

    req = _approval_store[action_id]
    if req.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Action already {req.status}"
        )

    req.status = "approved"
    req.decided_at = datetime.now(timezone.utc).isoformat()
    req.decided_by = decision.decided_by if decision else "human_operator"
    req.reason = decision.reason if decision else None

    return {
        "status": "approved",
        "action_id": action_id,
        "action": req.action,
        "tool": req.tool,
        "risk_level": req.risk_level,
        "decided_by": req.decided_by,
        "message": f"Action approved. Ready for execution.",
    }


@router.post("/reject/{action_id}")
def reject_action(action_id: str, decision: ApprovalDecision = None):
    """Reject a pending action."""
    if action_id not in _approval_store:
        raise HTTPException(status_code=404, detail=f"Approval {action_id} not found")

    req = _approval_store[action_id]
    if req.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Action already {req.status}"
        )

    req.status = "rejected"
    req.decided_at = datetime.now(timezone.utc).isoformat()
    req.decided_by = decision.decided_by if decision else "human_operator"
    req.reason = decision.reason if decision else "Rejected by operator"

    return {
        "status": "rejected",
        "action_id": action_id,
        "action": req.action,
        "reason": req.reason,
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