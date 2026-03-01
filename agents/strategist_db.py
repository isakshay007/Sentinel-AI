"""
SentinelAI — Strategist with DB Persistence
Runs full pipeline and stores strategy decisions in PostgreSQL.
"""

import asyncio
import json

from agents.strategist import full_pipeline
from backend.database import SessionLocal
from backend.models import AgentDecision, AuditLog


async def run_and_persist(service: str, scenario: str = None) -> dict:
    result = await full_pipeline(service, scenario)
    strat = result.get("strategist")

    if not strat:
        print("\n  No strategy produced. Nothing to persist.")
        return result

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

        for tc in strat.get("tool_calls", []):
            audit = AuditLog(
                agent_name="strategist",
                action="mcp_tool_call",
                mcp_server=tc.get("server"),
                tool_name=tc.get("tool"),
                input_data=tc.get("args", {}),
                output_data={"summary": tc.get("result_summary", "")},
            )
            db.add(audit)

        db.commit()
        print(f"\n  ✓ DB: strategist decision + {len(strat.get('tool_calls', []))} audit entries saved")

    except Exception as e:
        db.rollback()
        print(f"\n  ✗ DB error: {e}")
    finally:
        db.close()

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