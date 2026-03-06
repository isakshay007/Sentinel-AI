#!/usr/bin/env python3
"""
SentinelAI — Metrics CLI
Computes all metrics: incidents, agents, MTTR, approvals, eval, last_eval.

Run from project root (with venv activated):
  python scripts/metrics.py

Or via Docker (when stack is up):
  docker exec sentinel-backend python -m scripts.metrics
"""

import json
import os
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal
from backend.models import Incident, Approval, AgentDecision, AuditLog

OPEN_STATUSES = ("open", "investigating")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = PROJECT_ROOT / "evaluation" / "results"


def _load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def compute_db_metrics():
    db = SessionLocal()
    try:
        total = db.query(Incident).count()
        open_count = db.query(Incident).filter(Incident.status.in_(OPEN_STATUSES)).count()
        resolved = db.query(Incident).filter(Incident.status == "resolved").count()
        total_decisions = db.query(AgentDecision).count()
        total_tool_calls = db.query(AuditLog).count()

        mttr_minutes = None
        resolved_with_duration = (
            db.query(Incident)
            .filter(
                Incident.status == "resolved",
                Incident.detected_at.isnot(None),
                Incident.resolved_at.isnot(None),
            )
            .all()
        )
        if resolved_with_duration:
            total_sec = sum(
                (inc.resolved_at - inc.detected_at).total_seconds()
                for inc in resolved_with_duration
            )
            mttr_minutes = round(total_sec / len(resolved_with_duration) / 60, 1)

        approvals_processed = (
            db.query(Approval)
            .filter(
                Approval.status.in_(["approved", "rejected", "cancelled"]),
                Approval.requested_at.isnot(None),
                Approval.decided_at.isnot(None),
            )
            .all()
        )
        approval_latency_seconds = None
        if approvals_processed:
            total_sec = sum(
                (a.decided_at - a.requested_at).total_seconds()
                for a in approvals_processed
            )
            approval_latency_seconds = round(total_sec / len(approvals_processed), 1)

        auto_resolve_pct = round(resolved / total * 100, 1) if total else 0

        return {
            "total_incidents": total,
            "open_incidents": open_count,
            "resolved_incidents": resolved,
            "auto_resolve_pct": auto_resolve_pct,
            "mttr_minutes": mttr_minutes,
            "approvals_processed": len(approvals_processed),
            "approval_latency_seconds": approval_latency_seconds,
            "total_decisions": total_decisions,
            "total_tool_calls": total_tool_calls,
        }
    finally:
        db.close()


def compute_eval_metrics():
    out = {
        "safety_score": None,
        "eval_score": None,
        "last_eval_timestamp": None,
        "last_eval_scenarios_run": None,
        "last_eval_overall_score": None,
    }

    # Safety score from safety_report_*.json
    if EVAL_DIR.exists():
        safety_files = sorted(EVAL_DIR.glob("safety_report_*.json"), reverse=True)
        if safety_files:
            data = _load_json(safety_files[0])
            if data:
                out["safety_score"] = data.get("composite_safety_score")

        # Eval score from eval_*.json (eval_pipeline)
        eval_files = sorted(EVAL_DIR.glob("eval_*.json"), reverse=True)
        if eval_files:
            data = _load_json(eval_files[0])
            if data:
                results = data.get("results", {})
                all_scores = []
                for scenario_data in results.values():
                    all_scores.extend(scenario_data.get("scores", {}).values())
                if all_scores:
                    out["eval_score"] = round(sum(all_scores) / len(all_scores), 2)

        # Last eval from latest_eval.json (live_eval)
        latest = _load_json(EVAL_DIR / "latest_eval.json")
        if latest:
            out["last_eval_timestamp"] = latest.get("timestamp")
            out["last_eval_scenarios_run"] = latest.get("scenarios_run")
            out["last_eval_overall_score"] = latest.get("overall_score")

    return out


def main():
    try:
        db_m = compute_db_metrics()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Ensure DATABASE_URL is set and PostgreSQL is running.", file=sys.stderr)
        sys.exit(1)

    eval_m = compute_eval_metrics()

    print("\n  SentinelAI — All Metrics")
    print("  " + "─" * 50)
    print("  INCIDENTS")
    print("  " + "─" * 50)
    print(f"  Total Incidents:      {db_m['total_incidents']}")
    print(f"  Open Incidents:       {db_m['open_incidents']}")
    print(f"  Resolved Incidents:   {db_m['resolved_incidents']}")
    print(f"  Auto-Resolved %:      {db_m['auto_resolve_pct']}%")
    print(f"  MTTR (avg):           {db_m['mttr_minutes']} min" if db_m['mttr_minutes'] is not None else "  MTTR (avg):           —")
    print()
    print("  APPROVALS")
    print("  " + "─" * 50)
    print(f"  Approvals Processed:   {db_m['approvals_processed']}")
    print(f"  Approval Latency:      {db_m['approval_latency_seconds']}s" if db_m['approval_latency_seconds'] is not None else "  Approval Latency:      —")
    print()
    print("  AGENTS")
    print("  " + "─" * 50)
    print(f"  Total Decisions:       {db_m['total_decisions']}")
    print(f"  Total Tool Calls:      {db_m['total_tool_calls']}")
    print()
    print("  EVALUATION")
    print("  " + "─" * 50)
    print(f"  Safety Score:          {eval_m['safety_score']}" if eval_m['safety_score'] is not None else "  Safety Score:          —")
    print(f"  Eval Score:            {eval_m['eval_score']}" if eval_m['eval_score'] is not None else "  Eval Score:            —")
    print()
    print("  LAST LIVE EVAL (python -m evaluation.live_eval)")
    print("  " + "─" * 50)
    print(f"  Timestamp:             {eval_m['last_eval_timestamp'] or '—'}")
    print(f"  Scenarios Run:         {eval_m['last_eval_scenarios_run']}" if eval_m['last_eval_scenarios_run'] is not None else "  Scenarios Run:         —")
    last_score = eval_m['last_eval_overall_score']
    print(f"  Overall Score:         {f'{last_score*100:.0f}%' if last_score is not None else '—'}")
    print("  " + "─" * 50)
    print()


if __name__ == "__main__":
    main()
