"""
SentinelAI — A2A (Agent-to-Agent) Protocol
Implements agent cards, task lifecycle, and inter-agent communication
following the A2A specification under Linux Foundation.

Components:
  - AgentCard: JSON description of an agent's capabilities
  - Task: Unit of work with lifecycle (submitted → working → completed/failed)
  - A2AServer: Receives tasks from other agents
  - A2AClient: Discovers agents and sends tasks
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum


# =============================================================================
# TASK LIFECYCLE
# =============================================================================

class TaskStatus(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class Task:
    """A unit of work delegated between agents."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sender_agent: str = ""
    receiver_agent: str = ""
    skill_id: str = ""
    description: str = ""
    input_data: dict = field(default_factory=dict)
    output_data: dict = field(default_factory=dict)
    status: str = TaskStatus.SUBMITTED
    risk_level: str = "safe"
    requires_approval: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def update_status(self, status: str, output: dict = None, error: str = None):
        self.status = status
        self.updated_at = datetime.now(timezone.utc).isoformat()
        if output:
            self.output_data = output
        if error:
            self.error = error
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            self.completed_at = datetime.now(timezone.utc).isoformat()


# =============================================================================
# AGENT CARDS
# =============================================================================

@dataclass
class Skill:
    """A capability that an agent exposes."""
    id: str
    description: str
    input_schema: dict = field(default_factory=dict)
    risk_level: str = "safe"


@dataclass
class AgentCard:
    """JSON description of an agent's identity and capabilities."""
    name: str
    description: str
    url: str
    skills: List[Skill] = field(default_factory=list)
    version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "skills": [
                {"id": s.id, "description": s.description, "risk_level": s.risk_level}
                for s in self.skills
            ],
        }


# =============================================================================
# AGENT REGISTRY — Define all executor agent cards
# =============================================================================

AGENT_CARDS = {
    "ScaleAgent": AgentCard(
        name="ScaleAgent",
        description="Scales services up or down based on load requirements",
        url="http://localhost:8001/a2a",
        skills=[
            Skill(id="scale_up", description="Increase service replicas", risk_level="safe"),
            Skill(id="scale_down", description="Decrease service replicas", risk_level="risky"),
        ],
    ),
    "RestartAgent": AgentCard(
        name="RestartAgent",
        description="Performs graceful service restarts with connection draining",
        url="http://localhost:8002/a2a",
        skills=[
            Skill(id="restart_service", description="Graceful restart of a service", risk_level="risky"),
        ],
    ),
    "RollbackAgent": AgentCard(
        name="RollbackAgent",
        description="Rolls back deployments to previous known-good versions",
        url="http://localhost:8003/a2a",
        skills=[
            Skill(id="rollback_deployment", description="Roll back to previous version", risk_level="dangerous"),
        ],
    ),
    "NotifyAgent": AgentCard(
        name="NotifyAgent",
        description="Sends notifications and creates incident tickets",
        url="http://localhost:8004/a2a",
        skills=[
            Skill(id="send_notification", description="Send alert notification", risk_level="safe"),
            Skill(id="create_ticket", description="Create incident ticket", risk_level="safe"),
        ],
    ),
}


# =============================================================================
# A2A CLIENT — Strategist uses this to discover agents and send tasks
# =============================================================================

class A2AClient:
    """Client for discovering agents and delegating tasks."""

    def __init__(self):
        self.registry: Dict[str, AgentCard] = AGENT_CARDS
        self.tasks: Dict[str, Task] = {}

    def discover_agents(self, skill_id: str = None) -> List[AgentCard]:
        """Discover agents, optionally filtered by skill."""
        if not skill_id:
            return list(self.registry.values())

        matching = []
        for card in self.registry.values():
            for skill in card.skills:
                if skill.id == skill_id:
                    matching.append(card)
                    break
        return matching

    def create_task(
        self,
        receiver_agent: str,
        skill_id: str,
        description: str,
        input_data: dict,
        risk_level: str = "safe",
        requires_approval: bool = False,
    ) -> Task:
        """Create a new task for an agent."""
        task = Task(
            sender_agent="strategist",
            receiver_agent=receiver_agent,
            skill_id=skill_id,
            description=description,
            input_data=input_data,
            risk_level=risk_level,
            requires_approval=requires_approval,
        )
        self.tasks[task.id] = task
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def get_all_tasks(self) -> List[Task]:
        return list(self.tasks.values())

    def get_tasks_by_status(self, status: str) -> List[Task]:
        return [t for t in self.tasks.values() if t.status == status]


# =============================================================================
# A2A SERVER — Executor agents use this to receive and process tasks
# =============================================================================

class A2AServer:
    """Server that executor agents run to receive tasks."""

    def __init__(self, agent_card: AgentCard):
        self.card = agent_card
        self.pending_tasks: List[Task] = []
        self.completed_tasks: List[Task] = []

    def receive_task(self, task: Task) -> dict:
        """Receive a task from another agent."""
        # Validate skill exists
        valid_skills = [s.id for s in self.card.skills]
        if task.skill_id not in valid_skills:
            task.update_status(TaskStatus.FAILED, error=f"Unknown skill: {task.skill_id}")
            return {"status": "rejected", "error": f"Skill {task.skill_id} not found"}

        task.update_status(TaskStatus.WORKING)
        self.pending_tasks.append(task)
        return {"status": "accepted", "task_id": task.id}

    def complete_task(self, task_id: str, output: dict) -> dict:
        """Mark a task as completed with results."""
        for task in self.pending_tasks:
            if task.id == task_id:
                task.update_status(TaskStatus.COMPLETED, output=output)
                self.pending_tasks.remove(task)
                self.completed_tasks.append(task)
                return {"status": "completed", "task_id": task_id}
        return {"status": "error", "message": f"Task {task_id} not found"}

    def fail_task(self, task_id: str, error: str) -> dict:
        """Mark a task as failed."""
        for task in self.pending_tasks:
            if task.id == task_id:
                task.update_status(TaskStatus.FAILED, error=error)
                self.pending_tasks.remove(task)
                self.completed_tasks.append(task)
                return {"status": "failed", "task_id": task_id}
        return {"status": "error", "message": f"Task {task_id} not found"}


# =============================================================================
# CLI — Test the protocol
# =============================================================================

if __name__ == "__main__":
    print("\n  SentinelAI A2A Protocol Test")
    print("=" * 50)

    # Create client (Strategist)
    client = A2AClient()

    # Discover agents
    print("\n  Registered Agents:")
    for card in client.discover_agents():
        skills = ", ".join(s.id for s in card.skills)
        print(f"    - {card.name}: {skills}")

    # Find agent for scaling
    print("\n  Agents with 'scale_up' skill:")
    for card in client.discover_agents("scale_up"):
        print(f"    - {card.name}")

    # Create tasks
    print("\n  Creating tasks...")

    t1 = client.create_task(
        receiver_agent="NotifyAgent",
        skill_id="send_notification",
        description="Send critical alert about memory leak",
        input_data={"channel": "all", "message": "Memory leak in user-service", "severity": "critical"},
        risk_level="safe",
    )
    print(f"    Task 1: {t1.id[:12]}... → NotifyAgent (safe)")

    t2 = client.create_task(
        receiver_agent="ScaleAgent",
        skill_id="scale_up",
        description="Scale user-service to 5 replicas",
        input_data={"service": "user-service", "replicas": 5},
        risk_level="safe",
    )
    print(f"    Task 2: {t2.id[:12]}... → ScaleAgent (safe)")

    t3 = client.create_task(
        receiver_agent="RestartAgent",
        skill_id="restart_service",
        description="Restart user-service to clear memory",
        input_data={"service": "user-service", "reason": "memory leak"},
        risk_level="risky",
        requires_approval=True,
    )
    print(f"    Task 3: {t3.id[:12]}... → RestartAgent (risky, needs approval)")

    # Simulate server receiving tasks
    print("\n  Simulating task processing...")

    notify_server = A2AServer(AGENT_CARDS["NotifyAgent"])
    result = notify_server.receive_task(t1)
    print(f"    NotifyAgent received: {result['status']}")
    notify_server.complete_task(t1.id, {"notification_id": "notif-123", "delivered": True})
    print(f"    NotifyAgent completed: {t1.status}")

    scale_server = A2AServer(AGENT_CARDS["ScaleAgent"])
    result = scale_server.receive_task(t2)
    print(f"    ScaleAgent received: {result['status']}")
    scale_server.complete_task(t2.id, {"previous": 2, "new": 5})
    print(f"    ScaleAgent completed: {t2.status}")

    # Task lifecycle summary
    print("\n  Task Summary:")
    for task in client.get_all_tasks():
        print(f"    [{task.status:20s}] {task.receiver_agent:15s} → {task.description[:40]}")

    print(f"\n  Total tasks: {len(client.get_all_tasks())}")
    print(f"  Completed:   {len(client.get_tasks_by_status('completed'))}")
    print(f"  Awaiting:    {len(client.get_tasks_by_status('submitted'))}")
    print()