"""
SentinelAI — Incident State Machine
Manages valid status transitions for incidents.
Emits lifecycle events (#9, #19).
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from backend.database import SessionLocal
from backend.models import Incident, IncidentEvent
from backend.approval import get_pending

logger = logging.getLogger(__name__)

INCIDENT_STATES = ("open", "investigating", "resolved")

VALID_TRANSITIONS = {
    "open": ("investigating", "resolved"),
    "investigating": ("resolved",),
    "resolved": (),
}


def can_transition(current: str, new: str) -> bool:
    """Check if transition from current to new status is valid."""
    if current not in VALID_TRANSITIONS:
        return False
    return new in VALID_TRANSITIONS[current]


def transition_incident_status(
    incident_id: str,
    new_status: str,
) -> bool:
    """
    Transition incident to new status if valid.
    Returns True if transition was applied, False otherwise.
    """
    db = SessionLocal()
    try:
        inc = db.query(Incident).filter(Incident.id == incident_id).first()
        if not inc:
            return False
        current = inc.status or "open"
        if not can_transition(current, new_status):
            logger.warning("Invalid transition for incident %s: %s → %s (rejected)", incident_id, current, new_status)
            return False
        inc.status = new_status
        logger.info("Incident %s transitioned: %s → %s", incident_id, current, new_status)
        if new_status == "resolved":
            inc.resolved_at = datetime.now(timezone.utc)

        # Emit lifecycle event (#9, #19)
        ev = IncidentEvent(
            incident_id=incident_id,
            event_type="status_transition",
            payload={"from": current, "to": new_status},
        )
        db.add(ev)
        db.commit()

        return True
    except Exception as e:
        db.rollback()
        logger.exception("Transition failed for incident %s: %s", incident_id, e)
        return False
    finally:
        db.close()


def is_last_pending_for_incident(incident_id: str, action_id: str) -> bool:
    """
    True if approving action_id would leave no other pendings for this incident.
    Call BEFORE changing req.status to approved.
    """
    pending = get_pending()
    matching = [r for r in pending if r.incident_id == incident_id]
    return len(matching) == 1 and matching[0].id == action_id


def mark_investigating_if_open(incident_id: str) -> bool:
    """Set incident to investigating if currently open. Used after strategist completes."""
    return transition_incident_status(incident_id, "investigating")


def emit_incident_event(incident_id: Optional[str], event_type: str, payload: dict) -> None:
    """Emit event to single event store (#9, #19). Called from approval flow."""
    db = SessionLocal()
    try:
        ev = IncidentEvent(incident_id=incident_id, event_type=event_type, payload=payload)
        db.add(ev)
        db.commit()
    except Exception as e:
        logger.exception("Failed to emit event: %s", e)
        db.rollback()
    finally:
        db.close()
