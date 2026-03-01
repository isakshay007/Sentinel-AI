"""
SentinelAI — Database Seeder
Generates all mock scenarios and stores them in:
  1. JSON files in tests/fixtures/ (for quick access, version control)
  2. PostgreSQL (for agent queries via MCP tools)

Usage:
  python -m backend.seed_db              # Seed everything
  python -m backend.seed_db --json-only  # Only JSON fixtures
  python -m backend.seed_db --db-only    # Only PostgreSQL
"""

import json
import os
import argparse
from pathlib import Path
from datetime import datetime, timezone

from backend.database import SessionLocal, engine
from backend.models import Base, Incident, AuditLog
from backend.mock_data_generator import (
    MockDataGenerator, SCENARIO_REGISTRY, seed_all_fixtures
)


def seed_database(gen: MockDataGenerator):
    """Seed PostgreSQL with scenario data as Incident records."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        for scenario_type in SCENARIO_REGISTRY:
            data = gen.generate_scenario(scenario_type)

            # Create an Incident record for each scenario
            incident = Incident(
                title=f"[SEED] {scenario_type.replace('_', ' ').title()}",
                severity=data["expected_severity"],
                status="resolved",
                root_cause=data["expected_root_cause"],
                metadata_={
                    "scenario_type": data["scenario_type"],
                    "service": data["service"],
                    "description": data["description"],
                    "timeline_minutes": data["timeline_minutes"],
                    "incident_start_minute": data["incident_start_minute"],
                    "metrics_count": data["metrics_count"],
                    "logs_count": data["logs_count"],
                    "is_seed_data": True,
                },
            )
            db.add(incident)
            db.flush()  # Get the ID

            # Log the seeding action
            audit = AuditLog(
                agent_name="seed_script",
                action="seed_scenario",
                tool_name="mock_data_generator",
                input_data={"scenario_type": scenario_type},
                output_data={
                    "incident_id": incident.id,
                    "metrics_count": data["metrics_count"],
                    "logs_count": data["logs_count"],
                },
            )
            db.add(audit)

            print(f"  ✓ DB: {scenario_type} → Incident {incident.id[:8]}...")

        db.commit()
        print(f"\n  Database seeded with {len(SCENARIO_REGISTRY)} incidents")

    except Exception as e:
        db.rollback()
        print(f"  ✗ Database error: {e}")
        raise
    finally:
        db.close()


def verify_seed():
    """Quick verification that seeded data exists."""
    db = SessionLocal()
    try:
        incidents = db.query(Incident).filter(
            Incident.title.like("%[SEED]%")
        ).all()
        print(f"\n  Verification: {len(incidents)} seeded incidents in database")
        for inc in incidents:
            print(f"    • {inc.title} [{inc.severity}] — {inc.status}")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="SentinelAI Database Seeder")
    parser.add_argument("--json-only", action="store_true",
                        help="Only generate JSON fixtures")
    parser.add_argument("--db-only", action="store_true",
                        help="Only seed PostgreSQL")
    parser.add_argument("--output-dir", default="tests/fixtures",
                        help="Output directory for JSON fixtures")
    parser.add_argument("--verify", action="store_true",
                        help="Verify seeded data exists")
    args = parser.parse_args()

    gen = MockDataGenerator(seed=42)

    print("\n╔══════════════════════════════════════╗")
    print("║   SentinelAI — Seeding Mock Data     ║")
    print("╚══════════════════════════════════════╝\n")

    if args.verify:
        verify_seed()
        return

    if not args.db_only:
        print("── JSON Fixtures ──")
        seed_all_fixtures(args.output_dir)

    if not args.json_only:
        print("\n── PostgreSQL ──")
        seed_database(gen)
        verify_seed()

    print("\n✓ Seeding complete!\n")
    print("Next steps:")
    print("  • View fixtures:  ls tests/fixtures/")
    print("  • View in DB:     python -m backend.seed_db --verify")
    print("  • Test a scenario: python -m backend.mock_data_generator --scenario memory_leak\n")


if __name__ == "__main__":
    main()