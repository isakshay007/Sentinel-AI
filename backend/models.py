from sqlalchemy import Column, String, Float, DateTime, JSON, Integer, Text, Enum
from datetime import datetime, timezone
import uuid
from backend.database import Base

class Incident(Base):
    __tablename__ = "incidents"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False)
    severity = Column(String)  # low, medium, high, critical
    status = Column(String, default="open")  # open, investigating, resolved
    detected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime, nullable=True)
    root_cause = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)

class AgentDecision(Base):
    __tablename__ = "agent_decisions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    incident_id = Column(String, nullable=True)
    agent_name = Column(String, nullable=False)
    decision_type = Column(String)  # detect, diagnose, plan, execute
    reasoning = Column(Text)
    confidence = Column(Float)
    tool_calls = Column(JSON, default=list)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class EvalResult(Base):
    __tablename__ = "eval_results"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    model_name = Column(String)
    metric_name = Column(String)
    score = Column(Float)
    test_case_id = Column(String)
    details = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Approval(Base):
    """Persisted approval requests. Source of truth for approval history (#5, #11)."""
    __tablename__ = "approvals"
    id = Column(String, primary_key=True)
    incident_id = Column(String, nullable=True)
    agent_name = Column(String, nullable=False)
    action = Column(String, nullable=False)
    tool = Column(String, nullable=False)
    tool_args = Column(JSON, default=dict)
    risk_level = Column(String, default="risky")
    service = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending, approved, rejected
    requested_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(String, nullable=True)
    reason = Column(Text, nullable=True)


class IncidentEvent(Base):
    """Single event store for lifecycle transitions (#9, #19)."""
    __tablename__ = "incident_events"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    incident_id = Column(String, nullable=True)
    event_type = Column(String, nullable=False)  # status_transition, approval, tool_call
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    incident_id = Column(String, nullable=True)  # link to incident for trace view
    agent_name = Column(String)
    action = Column(String)
    mcp_server = Column(String, nullable=True)
    tool_name = Column(String, nullable=True)
    input_data = Column(JSON, default=dict)
    output_data = Column(JSON, default=dict)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))