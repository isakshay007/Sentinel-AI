"""
SentinelAI — Watcher Agent with DB Persistence
Runs the watcher and stores all results in PostgreSQL.
"""

import asyncio
import json
from datetime import datetime, timezone

from agents.watcher import run_watcher
from backend.database import SessionLocal
from backend.models import Incident, AgentDecision, AuditLog


async def run_and_persist(service: str, scenario: str = None) -> dict:
    result = await run_watcher(service, scenario)
    db = SessionLocal()

    try:
        # Save agent decision
        decision = AgentDecision(
            incident_id=result.get("incident_id"),
            agent_name="watcher",
            decision_type="detect",
            reasoning=json.dumps({
                "analysis": result.get("analysis"),
                "summary": result.get("summary"),
                "severity": result.get("severity"),
            }),
            confidence=result.get("confidence", 0.0),
            tool_calls=result.get("tool_calls", []),
        )
        db.add(decision)

        # Save incident if alert triggered
        if result.get("should_alert") and result.get("incident_id"):
            incident = Incident(
                id=result["incident_id"],
                title=f"[Watcher] {result.get('summary', 'Anomaly detected')}",
                severity=result.get("severity", "medium"),
                status="open",
                metadata_={
                    "detected_by": "watcher_agent",
                    "service": service,
                    "scenario": scenario,
                    "confidence": result.get("confidence"),
                    "tool_calls_count": len(result.get("tool_calls", [])),
                    "ticket_id": result.get("ticket_result", {}).get("ticket", {}).get("id"),
                },
            )
            db.add(incident)

        # Log each MCP tool call
        for tc in result.get("tool_calls", []):
            audit = AuditLog(
                agent_name="watcher",
                action="mcp_tool_call",
                mcp_server=tc.get("server"),
                tool_name=tc.get("tool"),
                input_data=tc.get("args", {}),
                output_data={"summary": tc.get("result_summary", "")},
            )
            db.add(audit)

        db.commit()
        print(f"\n  ✓ DB: decision + {len(result.get('tool_calls', []))} audit entries saved")
        if result.get("incident_id"):
            print(f"  ✓ DB: incident {result['incident_id'][:12]}... saved")

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

    print(f"\n  Running Watcher for {args.service}...")
    result = asyncio.run(run_and_persist(args.service, args.scenario))

    print(f"\n  Alert: {result.get('should_alert')} | Confidence: {result.get('confidence', 0):.0%}")
    print(f"  Summary: {result.get('summary', 'N/A')}")