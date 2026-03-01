"""
SentinelAI — Strategist with DB Persistence
Runs full pipeline and stores strategy decisions in PostgreSQL.
"""

import asyncio
import json

from agents.strategist import full_pipeline
from backend.database import SessionLocal
from backend.models import AgentDecision, AuditLog


def persist_strategist_result(strat: dict) -> None:
    """Persist strategist result to DB. Used by API pipeline."""
    db = SessionLocal()
    try:
        decision = AgentDecision(
            incident_id=strat.get("incident_id"),
            agent_name="strategist",
            decision_type="plan",
            reasoning=json.dumps({
                "selected_plan": strat.get("selected_plan", {}).get("name"),
                "total_plans": len(strat.get("plans", [])),
                "approved_actions": len(strat.get("approved_actions", [])),
                "pending_actions": len(strat.get("pending_actions", [])),
                "execution_results": strat.get("execution_results", []),
                "delegated_tasks": [
                    {"action": t.get("action"), "status": t.get("status"), "risk": t.get("risk_level")}
                    for t in strat.get("delegated_tasks", [])
                ],
            }),
            confidence=strat.get("diagnostician_confidence", 0.0),
            tool_calls=strat.get("tool_calls", []),
        )
        db.add(decision)
        incident_id_for_audit = strat.get("incident_id")
        for tc in strat.get("tool_calls", []):
            audit = AuditLog(
                incident_id=incident_id_for_audit,
                agent_name="strategist",
                action="mcp_tool_call",
                mcp_server=tc.get("server"),
                tool_name=tc.get("tool"),
                input_data=tc.get("args", {}),
                output_data={"summary": tc.get("result_summary", "")},
            )
            db.add(audit)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def run_and_persist(service: str, scenario: str = None) -> dict:
    result = await full_pipeline(service, scenario)
    strat = result.get("strategist")

    if not strat:
        print("\n  No strategy produced. Nothing to persist.")
        return result

    try:
        persist_strategist_result(strat)
        print(f"\n  ✓ DB: strategist decision + {len(strat.get('tool_calls', []))} audit entries saved")
    except Exception as e:
        print(f"\n  ✗ DB error: {e}")

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--service", default="user-service")
    parser.add_argument("--scenario", default=None)
    args = parser.parse_args()

    print(f"\n  Running full pipeline for {args.service}...")
    result = asyncio.run(run_and_persist(args.service, args.scenario))

    strat = result.get("strategist")
    if strat:
        selected = strat.get("selected_plan", {})
        print(f"\n  Plan: {selected.get('name', 'N/A')}")
        print(f"  Approved: {len(strat.get('approved_actions', []))}")
        print(f"  Pending:  {len(strat.get('pending_actions', []))}")