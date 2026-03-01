"""
SentinelAI — Diagnostician Agent with DB Persistence
Runs full Watcher → Diagnostician pipeline and stores everything in PostgreSQL.
"""

import asyncio
import json
from datetime import datetime, timezone

from agents.diagnostician import watcher_to_diagnostician
from backend.database import SessionLocal
from backend.models import AgentDecision, AuditLog


async def run_and_persist(service: str, scenario: str = None) -> dict:
    result = await watcher_to_diagnostician(service, scenario)
    diag = result.get("diagnostician")

    if not diag:
        print("\n  No diagnosis produced. Nothing to persist.")
        return result

    db = SessionLocal()
    try:
        # Save diagnostician decision
        decision = AgentDecision(
            incident_id=diag.get("incident_id"),
            agent_name="diagnostician",
            decision_type="diagnose",
            reasoning=json.dumps({
                "root_cause": diag.get("root_cause"),
                "hypothesis": diag.get("hypothesis"),
                "evidence_summary": diag.get("evidence_summary"),
                "diagnosis": diag.get("diagnosis"),
                "reasoning_chain": diag.get("reasoning_chain"),
                "iterations": diag.get("iteration"),
                "similar_incidents": [
                    s.get("metadata", {}).get("title")
                    for s in diag.get("similar_incidents", [])
                ],
            }),
            confidence=diag.get("confidence", 0.0),
            tool_calls=diag.get("tool_calls", []),
        )
        db.add(decision)

        # Log each MCP tool call
        for tc in diag.get("tool_calls", []):
            audit = AuditLog(
                agent_name="diagnostician",
                action="mcp_tool_call",
                mcp_server=tc.get("server"),
                tool_name=tc.get("tool"),
                input_data=tc.get("args", {}),
                output_data={"summary": tc.get("result_summary", "")},
            )
            db.add(audit)

        db.commit()
        print(f"\n  ✓ DB: diagnostician decision + {len(diag.get('tool_calls', []))} audit entries saved")

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

    print(f"\n  Running Watcher → Diagnostician for {args.service}...")
    result = asyncio.run(run_and_persist(args.service, args.scenario))

    diag = result.get("diagnostician")
    if diag:
        print(f"\n  Root Cause: {diag.get('root_cause', 'N/A')}")
        print(f"  Confidence: {diag.get('confidence', 0):.0%}")
        print(f"  Iterations: {diag.get('iteration', '?')}")