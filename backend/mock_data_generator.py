"""
SentinelAI — Mock Data Generator
Generates realistic, correlated DevOps telemetry data.

Design principles:
  - Metrics correlate (high memory → high CPU → slow responses → more errors)
  - Logs tell a coherent story with realistic service names and trace IDs
  - Incidents develop gradually, not instantly
  - Easy to add new scenarios via the SCENARIO_REGISTRY pattern

Usage:
  python -m backend.mock_data_generator                    # Print samples
  python -m backend.mock_data_generator --scenario memory_leak
  python -m backend.mock_data_generator --seed-all         # Generate all fixtures
"""

import random
import uuid
import json
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path


# =============================================================================
# CONFIGURATION — Realistic service topology
# =============================================================================

SERVICES = {
    "api-gateway": {
        "port": 8080,
        "depends_on": ["user-service", "payment-service", "inventory-service"],
        "normal_cpu": (15, 30),
        "normal_memory": (35, 50),
        "normal_latency": (80, 180),
        "normal_error_rate": (0.001, 0.008),
        "normal_rps": (200, 600),
    },
    "user-service": {
        "port": 8081,
        "depends_on": ["postgres-primary", "redis-cache"],
        "normal_cpu": (20, 40),
        "normal_memory": (40, 60),
        "normal_latency": (30, 90),
        "normal_error_rate": (0.001, 0.005),
        "normal_rps": (150, 400),
    },
    "payment-service": {
        "port": 8082,
        "depends_on": ["postgres-primary", "stripe-client"],
        "normal_cpu": (10, 25),
        "normal_memory": (30, 45),
        "normal_latency": (100, 250),
        "normal_error_rate": (0.0005, 0.003),
        "normal_rps": (50, 150),
    },
    "inventory-service": {
        "port": 8083,
        "depends_on": ["postgres-primary", "redis-cache"],
        "normal_cpu": (15, 35),
        "normal_memory": (35, 55),
        "normal_latency": (40, 120),
        "normal_error_rate": (0.001, 0.006),
        "normal_rps": (100, 300),
    },
}

# Realistic log message templates per severity and context
LOG_TEMPLATES = {
    "INFO": {
        "request": [
            "POST /api/v2/{endpoint} completed in {latency}ms — 200 OK",
            "GET /api/v2/{endpoint} completed in {latency}ms — 200 OK",
            "Request {trace_id} processed successfully by {handler}",
            "Health check passed — uptime {uptime}h, connections {conns}/{max_conns}",
            "Cache hit for key user:{user_id} — ttl {ttl}s remaining",
            "Database query executed in {query_time}ms — {rows} rows returned",
            "Connection pool stats: active={active}, idle={idle}, max={max_conns}",
        ],
        "system": [
            "GC completed — freed {freed_mb}MB in {gc_time}ms (gen {gc_gen})",
            "Config reloaded from /etc/sentinel/{service}.yaml",
            "Metrics flush: {metric_count} datapoints written to buffer",
            "TLS certificate valid — expires in {cert_days} days",
        ],
    },
    "WARN": {
        "performance": [
            "Response time elevated: {latency}ms exceeds p95 threshold of {threshold}ms",
            "Connection pool utilization at {pool_pct}% ({active}/{max_conns})",
            "Memory usage at {memory_pct}% — approaching warning threshold (85%)",
            "Request queue depth: {queue_depth} — above normal baseline of 10",
            "Slow query detected: SELECT * FROM {table} took {query_time}ms",
            "GC pause: {gc_time}ms — exceeds 200ms budget",
        ],
        "retry": [
            "Retry attempt {attempt}/3 for {upstream} — {reason}",
            "Circuit breaker HALF-OPEN for {upstream} — testing with probe request",
            "Rate limit approaching: {current}/{limit} requests in current window",
        ],
    },
    "ERROR": {
        "memory": [
            "java.lang.OutOfMemoryError: Java heap space — allocated {alloc_mb}MB/{max_mb}MB",
            "OOM kill: process {pid} ({process}) used {used_mb}MB, limit {limit_mb}MB",
            "Memory allocation failed: cannot allocate {req_mb}MB, only {avail_mb}MB available",
            "Heap dump written to /tmp/heapdump-{timestamp}.hprof ({dump_mb}MB)",
        ],
        "connection": [
            "ConnectionRefusedError: {upstream}:{port} — connection refused",
            "TimeoutError: {upstream} did not respond within {timeout}s",
            "ConnectionPoolExhausted: all {max_conns} connections in use, {waiting} waiting",
            "SSL handshake failed with {upstream}: certificate has expired",
        ],
        "application": [
            "NullPointerException in {handler}.process() at line {line}",
            "HTTP 500 Internal Server Error on {method} /api/v2/{endpoint} — trace_id={trace_id}",
            "Transaction rollback: {reason} — affected {rows} rows",
            "Unhandled exception in request pipeline: {exception_type}: {exception_msg}",
        ],
        "deployment": [
            "Readiness probe failed: HTTP GET /health returned 503 (attempt {attempt}/10)",
            "Container restart: exit code {exit_code} — back-off restarting",
            "Version mismatch: expected schema v{expected}, got v{actual}",
            "Migration failed: {migration_name} — {reason}",
        ],
    },
}


# =============================================================================
# DATA CLASSES — Structured output
# =============================================================================

@dataclass
class LogEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = ""
    service: str = ""
    severity: str = "INFO"
    message: str = ""
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    source_file: str = ""
    line_number: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class MetricPoint:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = ""
    service: str = ""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used_mb: float = 0.0
    memory_total_mb: float = 2048.0
    response_time_ms: float = 0.0
    response_time_p99_ms: float = 0.0
    error_rate: float = 0.0
    request_count: int = 0
    active_connections: int = 0
    gc_pause_ms: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class DeploymentEvent:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = ""
    service: str = ""
    version: str = ""
    previous_version: str = ""
    deployer: str = ""
    commit_sha: str = field(default_factory=lambda: uuid.uuid4().hex[:7])
    commit_message: str = ""
    status: str = "success"
    rollback_available: bool = True
    deploy_duration_seconds: int = 0
    changelog: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class IncidentScenario:
    scenario_type: str = ""
    service: str = ""
    description: str = ""
    expected_root_cause: str = ""
    expected_severity: str = "high"
    metrics: List[Dict] = field(default_factory=list)
    logs: List[Dict] = field(default_factory=list)
    deployments: List[Dict] = field(default_factory=list)
    timeline_minutes: int = 60
    incident_start_minute: int = 30

    def to_dict(self) -> Dict:
        return {
            "scenario_type": self.scenario_type,
            "service": self.service,
            "description": self.description,
            "expected_root_cause": self.expected_root_cause,
            "expected_severity": self.expected_severity,
            "timeline_minutes": self.timeline_minutes,
            "incident_start_minute": self.incident_start_minute,
            "metrics_count": len(self.metrics),
            "logs_count": len(self.logs),
            "deployments_count": len(self.deployments),
            "metrics": self.metrics,
            "logs": self.logs,
            "deployments": self.deployments,
        }


# =============================================================================
# TEMPLATE ENGINE — Makes log messages feel real
# =============================================================================

class LogTemplateEngine:
    """Fills log templates with realistic, contextually appropriate values."""

    ENDPOINTS = ["users", "users/profile", "orders", "orders/status",
                 "payments/charge", "payments/refund", "inventory/check",
                 "inventory/reserve", "auth/token", "health"]
    HANDLERS = ["RequestHandler", "AuthMiddleware", "PaymentProcessor",
                "OrderService", "InventoryManager", "CacheLayer", "ConnectionPool"]
    TABLES = ["users", "orders", "payments", "inventory", "sessions", "audit_log"]
    UPSTREAMS = ["postgres-primary", "redis-cache", "stripe-client",
                 "user-service", "payment-service", "inventory-service"]
    DEPLOYERS = ["alice.chen", "bob.kumar", "ci-pipeline", "maria.santos", "deploy-bot"]

    @classmethod
    def fill(cls, template: str, context: Dict = None) -> str:
        ctx = context or {}
        defaults = {
            "endpoint": random.choice(cls.ENDPOINTS),
            "handler": random.choice(cls.HANDLERS),
            "table": random.choice(cls.TABLES),
            "upstream": random.choice(cls.UPSTREAMS),
            "trace_id": uuid.uuid4().hex[:12],
            "user_id": random.randint(10000, 99999),
            "latency": ctx.get("latency", random.randint(50, 200)),
            "threshold": 500,
            "uptime": random.randint(1, 720),
            "conns": random.randint(5, 40),
            "active": random.randint(5, 40),
            "idle": random.randint(2, 15),
            "max_conns": 50,
            "ttl": random.randint(10, 3600),
            "query_time": ctx.get("query_time", random.randint(1, 50)),
            "rows": random.randint(1, 1000),
            "freed_mb": random.randint(10, 200),
            "gc_time": ctx.get("gc_time", random.randint(5, 50)),
            "gc_gen": random.choice([0, 1, 2]),
            "service": ctx.get("service", "api-gateway"),
            "metric_count": random.randint(50, 500),
            "cert_days": random.randint(30, 365),
            "memory_pct": ctx.get("memory_pct", random.randint(40, 60)),
            "pool_pct": ctx.get("pool_pct", random.randint(40, 70)),
            "queue_depth": ctx.get("queue_depth", random.randint(1, 10)),
            "attempt": random.randint(1, 3),
            "reason": random.choice(["connection timeout", "socket hang up",
                                      "ECONNREFUSED", "read ETIMEDOUT"]),
            "current": random.randint(80, 95),
            "limit": 100,
            "alloc_mb": ctx.get("alloc_mb", random.randint(1800, 2048)),
            "max_mb": 2048,
            "used_mb": ctx.get("used_mb", random.randint(1800, 2048)),
            "limit_mb": 2048,
            "req_mb": random.randint(50, 256),
            "avail_mb": ctx.get("avail_mb", random.randint(5, 50)),
            "dump_mb": random.randint(500, 1500),
            "pid": random.randint(1000, 9999),
            "process": random.choice(["java", "node", "python3", "gunicorn"]),
            "port": ctx.get("port", random.choice([5432, 6379, 8080, 8081])),
            "timeout": random.choice([5, 10, 30]),
            "waiting": random.randint(5, 50),
            "method": random.choice(["GET", "POST", "PUT", "DELETE"]),
            "line": random.randint(50, 500),
            "exception_type": random.choice(["ValueError", "KeyError",
                                              "RuntimeError", "IOError"]),
            "exception_msg": random.choice(["unexpected null value",
                                             "invalid state transition",
                                             "resource not available"]),
            "exit_code": random.choice([1, 137, 143]),
            "expected": random.randint(10, 20),
            "actual": random.randint(5, 9),
            "migration_name": f"20260115_{random.randint(1,5)}_add_index",
            "timestamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        }
        defaults.update(ctx)

        try:
            return template.format(**defaults)
        except KeyError:
            return template


# =============================================================================
# CORE GENERATOR
# =============================================================================

class MockDataGenerator:
    """
    Generates realistic, correlated DevOps telemetry.
    All data follows realistic patterns and service topology.
    """

    def __init__(self, seed: int = None):
        if seed is not None:
            random.seed(seed)
        self.template_engine = LogTemplateEngine()

    # --- Individual generators ---

    def generate_log_entry(self, service: str = None, severity: str = None,
                            timestamp: datetime = None, context: Dict = None) -> Dict:
        service = service or random.choice(list(SERVICES.keys()))
        severity = severity or random.choices(
            ["INFO", "WARN", "ERROR"], weights=[75, 18, 7]
        )[0]
        timestamp = timestamp or datetime.now(timezone.utc)

        # Pick a subcategory and template
        subcategories = list(LOG_TEMPLATES[severity].keys())
        subcat = random.choice(subcategories)
        template = random.choice(LOG_TEMPLATES[severity][subcat])

        ctx = {"service": service}
        if context:
            ctx.update(context)

        source_files = {
            "INFO": ["server.py", "middleware.py", "health.py", "cache.py"],
            "WARN": ["monitor.py", "pool.py", "circuit_breaker.py", "gc.py"],
            "ERROR": ["handler.py", "connection.py", "transaction.py", "deploy.py"],
        }

        entry = LogEntry(
            timestamp=timestamp.isoformat(),
            service=service,
            severity=severity,
            message=self.template_engine.fill(template, ctx),
            source_file=random.choice(source_files.get(severity, ["app.py"])),
            line_number=random.randint(20, 500),
        )
        return entry.to_dict()

    def generate_metrics(self, service: str = None,
                          timestamp: datetime = None,
                          anomaly: str = None,
                          anomaly_progress: float = 0.0) -> Dict:
        """
        Generate a single metric point.
        
        Args:
            anomaly_progress: 0.0 = normal, 1.0 = full anomaly severity.
                             Allows gradual degradation.
        """
        service = service or random.choice(list(SERVICES.keys()))
        timestamp = timestamp or datetime.now(timezone.utc)
        svc = SERVICES[service]
        p = anomaly_progress  # shorthand

        # Base values with small natural fluctuations
        cpu = random.uniform(*svc["normal_cpu"])
        mem = random.uniform(*svc["normal_memory"])
        lat = random.uniform(*svc["normal_latency"])
        err = random.uniform(*svc["normal_error_rate"])
        rps = random.randint(*svc["normal_rps"])

        if anomaly == "memory_leak":
            # Memory climbs gradually; CPU follows; latency increases as GC thrashes
            mem = svc["normal_memory"][0] + p * (98 - svc["normal_memory"][0])
            cpu = svc["normal_cpu"][0] + p * 55  # CPU rises due to GC
            lat = svc["normal_latency"][0] + p * 3000  # GC pauses slow everything
            err = svc["normal_error_rate"][0] + max(0, p - 0.6) * 0.3  # Errors spike late
            gc_pause = 5 + p * 800  # GC pauses get brutal

        elif anomaly == "bad_deployment":
            # Instant degradation after deploy: errors spike, latency jumps
            err = svc["normal_error_rate"][0] + p * 0.35
            lat = svc["normal_latency"][0] + p * 5000
            cpu = svc["normal_cpu"][0] + p * 20  # Moderate CPU increase
            rps = int(rps * (1 - p * 0.4))  # Throughput drops as requests fail
            gc_pause = random.uniform(5, 30)

        elif anomaly == "api_timeout":
            # Upstream dependency dies: timeouts cascade
            lat = svc["normal_latency"][0] + p * 25000  # Up to 25s timeout
            err = svc["normal_error_rate"][0] + p * 0.25
            # CPU stays moderate (threads are just waiting)
            cpu = svc["normal_cpu"][0] + p * 10
            gc_pause = random.uniform(5, 30)

        else:
            gc_pause = random.uniform(2, 30)

        # Add natural noise (±5%) to all values
        noise = lambda v, pct=0.05: v * random.uniform(1 - pct, 1 + pct)

        point = MetricPoint(
            timestamp=timestamp.isoformat(),
            service=service,
            cpu_percent=round(min(noise(cpu), 100), 2),
            memory_percent=round(min(noise(mem), 99.5), 2),
            memory_used_mb=round(min(noise(mem), 99.5) / 100 * 2048, 1),
            response_time_ms=round(max(noise(lat), 1), 1),
            response_time_p99_ms=round(max(noise(lat * 2.5), 5), 1),
            error_rate=round(min(max(noise(err), 0), 1.0), 5),
            request_count=max(int(noise(rps, 0.1)), 10),
            active_connections=random.randint(5, 45),
            gc_pause_ms=round(gc_pause, 1),
        )
        return point.to_dict()

    def generate_deployment(self, service: str = None,
                             timestamp: datetime = None,
                             success: bool = True) -> Dict:
        service = service or random.choice(list(SERVICES.keys()))
        timestamp = timestamp or datetime.now(timezone.utc)

        major, minor = random.randint(2, 4), random.randint(0, 15)
        patch = random.randint(0, 30)
        prev_patch = max(0, patch - random.randint(1, 5))

        changelogs = [
            "fix: resolve connection pool leak under high concurrency",
            "feat: add request batching for inventory lookups",
            "fix: handle null user_id in payment flow",
            "refactor: migrate to async database driver",
            "fix: correct timeout handling for upstream calls",
            "feat: add circuit breaker for external APIs",
            "chore: update dependencies to latest patch versions",
            "fix: resolve race condition in session management",
            "perf: optimize N+1 query in order listing endpoint",
        ]

        event = DeploymentEvent(
            timestamp=timestamp.isoformat(),
            service=service,
            version=f"v{major}.{minor}.{patch}",
            previous_version=f"v{major}.{minor}.{prev_patch}",
            deployer=random.choice(LogTemplateEngine.DEPLOYERS),
            commit_message=random.choice(changelogs),
            status="success" if success else "failed",
            deploy_duration_seconds=random.randint(30, 180),
            changelog=random.sample(changelogs, k=random.randint(1, 3)),
        )
        return event.to_dict()

    # --- Scenario generators ---

    def generate_scenario(self, scenario_type: str,
                           timeline_minutes: int = 60) -> Dict:
        """
        Generate a complete incident scenario with correlated, gradual data.
        
        Each scenario has:
          - A normal baseline period
          - A gradual onset
          - A peak incident period
          - Correlated logs that match the metric degradation
        """
        generator = SCENARIO_REGISTRY.get(scenario_type)
        if not generator:
            raise ValueError(
                f"Unknown scenario: {scenario_type}. "
                f"Available: {list(SCENARIO_REGISTRY.keys())}"
            )
        return generator(self, timeline_minutes)

    def _scenario_memory_leak(self, timeline_minutes: int = 60) -> Dict:
        """
        Memory leak in user-service.
        
        Timeline:
          min 0-20:  Normal operation
          min 20-25: Memory starts climbing (subtle)
          min 25-45: Steady increase, WARN logs appear
          min 45-55: Critical levels, ERROR logs, GC thrashing
          min 55-60: OOM kills, service degraded
        """
        service = "user-service"
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=timeline_minutes)
        metrics, logs, deploys = [], [], []

        for minute in range(timeline_minutes):
            ts = start + timedelta(minutes=minute)

            # Calculate anomaly progress (0.0 = normal, 1.0 = peak)
            if minute < 20:
                progress = 0.0
            elif minute < 45:
                progress = (minute - 20) / 25  # Linear ramp 0→1 over 25 min
            else:
                progress = min(1.0, 0.8 + (minute - 45) * 0.04)  # Plateau near max

            # Metrics every minute
            m = self.generate_metrics(service, ts, "memory_leak", progress)
            metrics.append(m)

            # Logs — frequency and severity increase with progress
            if progress == 0:
                # Normal: occasional INFO logs
                if random.random() < 0.3:
                    logs.append(self.generate_log_entry(service, "INFO", ts))
            elif progress < 0.5:
                # Early warning: some WARN logs mixed with INFO
                logs.append(self.generate_log_entry(service, "INFO", ts))
                if random.random() < 0.4:
                    ctx = {"memory_pct": int(m["memory_percent"]),
                           "gc_time": int(m["gc_pause_ms"])}
                    logs.append(self.generate_log_entry(service, "WARN", ts, ctx))
            elif progress < 0.8:
                # Escalating: frequent WARNs, some ERRORs
                if random.random() < 0.6:
                    ctx = {"memory_pct": int(m["memory_percent"]),
                           "pool_pct": random.randint(70, 90)}
                    logs.append(self.generate_log_entry(service, "WARN", ts, ctx))
                if random.random() < 0.3:
                    ctx = {"used_mb": int(m["memory_used_mb"]),
                           "alloc_mb": int(m["memory_used_mb"])}
                    logs.append(self.generate_log_entry(service, "ERROR", ts, ctx))
            else:
                # Critical: ERROR storm
                ctx = {"used_mb": int(m["memory_used_mb"]),
                       "avail_mb": int(2048 - m["memory_used_mb"])}
                logs.append(self.generate_log_entry(service, "ERROR", ts, ctx))
                if random.random() < 0.5:
                    logs.append(self.generate_log_entry(service, "ERROR", ts, ctx))
                # Cascading: downstream services see connection errors
                if random.random() < 0.3:
                    logs.append(self.generate_log_entry(
                        "api-gateway", "ERROR", ts,
                        {"upstream": service, "port": 8081}
                    ))

        scenario = IncidentScenario(
            scenario_type="memory_leak",
            service=service,
            description=(
                "Gradual memory leak in user-service caused by unreleased "
                "database connections in the session handler. Memory climbs from "
                "~45% to 98% over 40 minutes, causing GC thrashing, increased "
                "latency, and eventual OOM kills."
            ),
            expected_root_cause="Memory leak in connection pool — connections not released after timeout",
            expected_severity="critical",
            metrics=metrics,
            logs=sorted(logs, key=lambda x: x["timestamp"]),
            timeline_minutes=timeline_minutes,
            incident_start_minute=20,
        )
        return scenario.to_dict()

    def _scenario_bad_deployment(self, timeline_minutes: int = 60) -> Dict:
        """
        Bad deployment to payment-service.
        
        Timeline:
          min 0-28:  Normal operation, stable metrics
          min 28:    Deployment event (v3.8.12 → v3.8.13)
          min 28-32: Brief settling period (looks OK initially)
          min 32-60: Error rate spikes, latency jumps, throughput drops
        """
        service = "payment-service"
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=timeline_minutes)
        metrics, logs, deploys = [], [], []

        deploy_minute = 28
        degrade_start = 32

        # The deployment event
        deploy_ts = start + timedelta(minutes=deploy_minute)
        deploy = self.generate_deployment(service, deploy_ts, success=True)
        deploy["version"] = "v3.8.13"
        deploy["previous_version"] = "v3.8.12"
        deploy["commit_message"] = "refactor: migrate to async database driver"
        deploy["changelog"] = [
            "refactor: migrate to async database driver",
            "fix: handle null user_id in payment flow",
            "chore: update dependencies to latest patch versions",
        ]
        deploys.append(deploy)

        for minute in range(timeline_minutes):
            ts = start + timedelta(minutes=minute)

            if minute < deploy_minute:
                progress = 0.0
            elif minute < degrade_start:
                progress = 0.05  # Barely noticeable
            else:
                # Rapid degradation after the grace period
                progress = min(1.0, (minute - degrade_start) / 15)

            m = self.generate_metrics(service, ts, "bad_deployment", progress)
            metrics.append(m)

            # Logs
            if progress == 0:
                if random.random() < 0.2:
                    logs.append(self.generate_log_entry(service, "INFO", ts))
            elif progress < 0.1:
                # Deploy happening
                logs.append(self.generate_log_entry(
                    service, "INFO", ts,
                    {"service": service}
                ))
            else:
                # Post-deploy degradation
                if random.random() < 0.4:
                    ctx = {"latency": int(m["response_time_ms"])}
                    logs.append(self.generate_log_entry(service, "WARN", ts, ctx))
                if random.random() < progress * 0.8:
                    logs.append(self.generate_log_entry(service, "ERROR", ts))
                # Other services see payment-service errors
                if random.random() < progress * 0.3:
                    logs.append(self.generate_log_entry(
                        "api-gateway", "ERROR", ts,
                        {"upstream": service, "port": 8082}
                    ))

        scenario = IncidentScenario(
            scenario_type="bad_deployment",
            service=service,
            description=(
                "Deployment v3.8.13 to payment-service introduced a regression "
                "in the async database driver migration. The service appeared "
                "healthy for ~4 minutes post-deploy before error rates spiked "
                "to 35% and response times jumped to 5000ms+."
            ),
            expected_root_cause="Regression in v3.8.13 — async DB driver incompatible with connection pool config",
            expected_severity="critical",
            metrics=metrics,
            logs=sorted(logs, key=lambda x: x["timestamp"]),
            deployments=deploys,
            timeline_minutes=timeline_minutes,
            incident_start_minute=degrade_start,
        )
        return scenario.to_dict()

    def _scenario_api_timeout(self, timeline_minutes: int = 60) -> Dict:
        """
        Upstream dependency (redis-cache) becomes unresponsive.
        
        Timeline:
          min 0-35:  Normal operation
          min 35-38: Redis starts responding slowly (network issue)
          min 38-60: Redis completely unresponsive, all dependent services
                     experience timeouts cascading through the stack
        """
        service = "api-gateway"
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=timeline_minutes)
        metrics, logs = [], []

        for minute in range(timeline_minutes):
            ts = start + timedelta(minutes=minute)

            if minute < 35:
                progress = 0.0
            elif minute < 38:
                progress = (minute - 35) / 6  # Slow onset
            else:
                progress = min(1.0, 0.5 + (minute - 38) * 0.05)

            # api-gateway metrics (primary victim)
            m = self.generate_metrics(service, ts, "api_timeout", progress)
            metrics.append(m)

            # Also generate metrics for dependent services
            if progress > 0.3:
                for dep_svc in ["user-service", "inventory-service"]:
                    dep_m = self.generate_metrics(
                        dep_svc, ts, "api_timeout", progress * 0.7
                    )
                    metrics.append(dep_m)

            # Logs
            if progress == 0:
                if random.random() < 0.2:
                    logs.append(self.generate_log_entry(service, "INFO", ts))
            elif progress < 0.4:
                ctx = {"upstream": "redis-cache", "port": 6379,
                       "latency": int(m["response_time_ms"])}
                if random.random() < 0.6:
                    logs.append(self.generate_log_entry(service, "WARN", ts, ctx))
            else:
                ctx = {"upstream": "redis-cache", "port": 6379,
                       "timeout": 30}
                logs.append(self.generate_log_entry(service, "ERROR", ts, ctx))
                if random.random() < 0.5:
                    logs.append(self.generate_log_entry(
                        "user-service", "ERROR", ts,
                        {"upstream": "redis-cache", "port": 6379}
                    ))
                if random.random() < 0.3:
                    logs.append(self.generate_log_entry(
                        "inventory-service", "WARN", ts,
                        {"upstream": "redis-cache", "latency": random.randint(5000, 15000)}
                    ))

        scenario = IncidentScenario(
            scenario_type="api_timeout",
            service=service,
            description=(
                "Redis cache became unresponsive due to a network partition. "
                "This caused cascading timeouts across api-gateway, user-service, "
                "and inventory-service. Response times jumped from ~150ms to 25s+ "
                "with error rates reaching 25%."
            ),
            expected_root_cause="Redis cache network partition — all cache-dependent services affected",
            expected_severity="high",
            metrics=metrics,
            logs=sorted(logs, key=lambda x: x["timestamp"]),
            timeline_minutes=timeline_minutes,
            incident_start_minute=35,
        )
        return scenario.to_dict()


# =============================================================================
# SCENARIO REGISTRY — Add new scenarios here
# =============================================================================

SCENARIO_REGISTRY = {
    "memory_leak": MockDataGenerator._scenario_memory_leak,
    "bad_deployment": MockDataGenerator._scenario_bad_deployment,
    "api_timeout": MockDataGenerator._scenario_api_timeout,
}


# =============================================================================
# CLI
# =============================================================================

def seed_all_fixtures(output_dir: str = "tests/fixtures"):
    """Generate all scenario fixtures as JSON files."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    gen = MockDataGenerator(seed=42)  # Reproducible

    for scenario_type in SCENARIO_REGISTRY:
        data = gen.generate_scenario(scenario_type)
        filepath = os.path.join(output_dir, f"{scenario_type}.json")
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  ✓ {scenario_type}: {data['metrics_count']} metrics, "
              f"{data['logs_count']} logs, {data.get('deployments_count', 0)} deploys "
              f"→ {filepath}")

    # Also create a combined summary
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenarios": list(SCENARIO_REGISTRY.keys()),
        "services": list(SERVICES.keys()),
    }
    with open(os.path.join(output_dir, "_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  ✓ Summary → {output_dir}/_summary.json")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SentinelAI Mock Data Generator")
    parser.add_argument("--scenario", choices=list(SCENARIO_REGISTRY.keys()),
                        help="Generate a specific scenario")
    parser.add_argument("--seed-all", action="store_true",
                        help="Generate all fixture files")
    parser.add_argument("--sample", action="store_true",
                        help="Print sample data from each generator")
    parser.add_argument("--output-dir", default="tests/fixtures",
                        help="Output directory for fixtures")
    args = parser.parse_args()

    gen = MockDataGenerator(seed=42)

    if args.seed_all:
        print("\nGenerating all scenario fixtures...\n")
        seed_all_fixtures(args.output_dir)

    elif args.scenario:
        print(f"\n=== Scenario: {args.scenario} ===\n")
        data = gen.generate_scenario(args.scenario)
        print(f"Service:        {data['service']}")
        print(f"Description:    {data['description']}")
        print(f"Root cause:     {data['expected_root_cause']}")
        print(f"Severity:       {data['expected_severity']}")
        print(f"Timeline:       {data['timeline_minutes']} minutes")
        print(f"Incident start: minute {data['incident_start_minute']}")
        print(f"Metrics:        {data['metrics_count']} points")
        print(f"Logs:           {data['logs_count']} entries")
        print(f"Deployments:    {data.get('deployments_count', 0)}")

        # Show metric progression
        print(f"\n--- Metric Progression (every 10 min) ---")
        for i in range(0, len(data["metrics"]), 10):
            m = data["metrics"][i]
            if m["service"] == data["service"]:
                print(f"  min {i:3d}: CPU={m['cpu_percent']:5.1f}%  "
                      f"MEM={m['memory_percent']:5.1f}%  "
                      f"Latency={m['response_time_ms']:8.1f}ms  "
                      f"Errors={m['error_rate']:.4f}")

        # Show last 5 logs
        print(f"\n--- Last 5 Logs ---")
        for log in data["logs"][-5:]:
            print(f"  [{log['severity']:5s}] {log['service']:20s} | {log['message'][:90]}")

    elif args.sample:
        print("\n=== Sample Log Entry ===")
        print(json.dumps(gen.generate_log_entry(), indent=2))

        print("\n=== Sample Metrics (normal) ===")
        print(json.dumps(gen.generate_metrics(), indent=2))

        print("\n=== Sample Metrics (memory_leak at 70% progress) ===")
        print(json.dumps(gen.generate_metrics(
            "user-service", anomaly="memory_leak", anomaly_progress=0.7
        ), indent=2))

        print("\n=== Sample Deployment ===")
        print(json.dumps(gen.generate_deployment(), indent=2))

    else:
        parser.print_help()
        print("\n\nQuick start:")
        print("  python -m backend.mock_data_generator --sample")
        print("  python -m backend.mock_data_generator --scenario memory_leak")
        print("  python -m backend.mock_data_generator --seed-all")