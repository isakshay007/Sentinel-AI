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


def persist_watcher_result(result: dict, service: str, scenario: str = None) -> None:
    """Persist watcher result to DB (incident, decision, audits). Used by API pipeline."""
    db = SessionLocal()
    try:
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

        # Log each MCP tool call (link to incident when alert triggered)
        incident_id_for_audit = result.get("incident_id") if result.get("should_alert") else None
        for tc in result.get("tool_calls", []):
            audit = AuditLog(
                incident_id=incident_id_for_audit,
                agent_name="watcher",
                action="mcp_tool_call",
                mcp_server=tc.get("server"),
                tool_name=tc.get("tool"),
                input_data=tc.get("args", {}),
                output_data={"summary": tc.get("result_summary", "")},
            )
            db.add(audit)

        db.commit()

    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


async def run_and_persist(service: str, scenario: str = None) -> dict:
    result = await run_watcher(service, scenario)
    try:
        persist_watcher_result(result, service, scenario)
        print(f"\n  ✓ DB: decision + {len(result.get('tool_calls', []))} audit entries saved")
        if result.get("incident_id"):
            print(f"  ✓ DB: incident {result['incident_id'][:12]}... saved")
    except Exception as e:
        print(f"\n  ✗ DB error: {e}")
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