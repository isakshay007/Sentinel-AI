"""
SentinelAI — Development-Only API
Reset endpoint for clean debugging. Only registered when SENTINEL_DEV_MODE=1.
DO NOT use in production.
"""

import logging
import os
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/dev", tags=["dev"])
logger = logging.getLogger(__name__)

_DEV_ENABLED = os.getenv("SENTINEL_DEV_MODE", "0") == "1"


@router.post("/reset")
def dev_reset():
    """
    DEVELOPMENT ONLY: Reset database, clear approvals, and re-seed fixtures (#14).
    Deletes all rows from incidents, agent_decisions, audit_logs, eval_results, approvals, incident_events.
    Re-seeds fixtures (JSON + DB) for clean state.
    Requires SENTINEL_DEV_MODE=1 (disabled by default in production).
    """
    if not _DEV_ENABLED:
        raise HTTPException(status_code=403, detail="Dev reset disabled. Set SENTINEL_DEV_MODE=1 to enable.")

    from backend.database import SessionLocal
    from backend.models import Incident, AgentDecision, AuditLog, EvalResult, Approval, IncidentEvent
    from backend.approval import clear_approval_store
    from backend.seed_db import seed_database
    from backend.mock_data_generator import MockDataGenerator, seed_all_fixtures

    db = SessionLocal()
    try:
        db.query(IncidentEvent).delete()
        db.query(Approval).delete()
        db.query(AuditLog).delete()
        db.query(AgentDecision).delete()
        db.query(EvalResult).delete()
        db.query(Incident).delete()
        db.commit()
        logger.info("DEV RESET: database cleared")
    except Exception as e:
        db.rollback()
        logger.exception("DEV RESET failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

    clear_approval_store(all_=True)

    # Re-seed fixtures (#14)
    try:
        seed_all_fixtures("tests/fixtures")
        gen = MockDataGenerator(seed=42)
        seed_database(gen)
        logger.info("DEV RESET: fixtures re-seeded")
    except Exception as e:
        logger.warning("Fixture re-seed failed (non-fatal): %s", e)

    return {"status": "database reset and fixtures re-seeded"}
