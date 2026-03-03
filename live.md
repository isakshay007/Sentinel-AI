# SentinelAI — Live Data Implementation Guide

## For Cursor: Step-by-step instructions to transform SentinelAI from mock data to live infrastructure monitoring with real AI agent decisions.

---

## OVERVIEW: What We're Building

Transform SentinelAI from fixture-based mock scenarios into a live infrastructure monitoring platform where:

1. Real microservices run in Docker, exposing real Prometheus metrics
2. Watcher agent continuously polls Prometheus and auto-detects anomalies (no "Run Scenario" button)
3. Diagnostician autonomously decides what to investigate based on raw metric patterns (no scenario hints)
4. Strategist generates context-aware action plans based on diagnosis
5. Executor performs real Docker API actions (restart, scale, flush cache) when human approves
6. Watcher verifies the fix worked by checking metrics post-remediation
7. "Inject Fault" button replaces "Run Scenario" — it breaks real services, then AI detects and responds

**No mock data. No fixtures. Live only.**

---

## SCENARIO ANALYSIS: What Can Go Wrong and How Agents Solve It

### Our Infrastructure

```
user-service (port 8001)
  └─ depends on: Redis (caching)
  └─ exposes: /users CRUD endpoints

payment-service (port 8002)
  └─ depends on: Redis (caching) + PostgreSQL (data)
  └─ exposes: /payments endpoints

api-gateway (port 8003)
  └─ depends on: user-service + payment-service + Redis (response cache)
  └─ exposes: /api/* proxy endpoints
```

### What Our Executor Can ACTUALLY Do (Docker API only)

```
✅ restart_service(service)    → docker container restart (clears memory, resets connections)
✅ scale_service(service, N)   → docker-compose up --scale service=N (add replicas)
✅ flush_cache()               → docker exec redis redis-cli FLUSHALL (clear Redis)
```

We CANNOT do: rollback_deployment (no multiple image versions), update_config (no config management), or modify code. Remove all references to rollback_deployment and update_config from the codebase.

### The 5 Fault Injection Scenarios (only these 5)

Each scenario below is fully validated: we can inject it, detect it, diagnose it, plan for it, and fix it with our actual tools.

---

#### SCENARIO 1: Memory Leak on user-service

**Inject:**
```
POST /chaos/memory on user-service
→ stress-ng --vm 1 --vm-bytes 90% --timeout 120
→ Also: background task inflates db_connections_active gauge and gc_pause_ms gauge
→ Also: POST /users starts returning 500 "OutOfMemoryError" ~30-50% of the time
→ Also: structured error logs written: {"level":"ERROR","message":"OutOfMemoryError: unable to allocate buffer for connection pool","service":"user-service"}
```

**What Prometheus shows (Watcher detects):**
```
service_memory_percent{service="user-service"} = 92% (threshold: 85%) ← ANOMALOUS
service_cpu_percent{service="user-service"} = 75% (threshold: 80%) ← ELEVATED (GC thrashing)
error_rate = 0.35 (threshold: 0.10) ← ANOMALOUS
response_time_ms = 3800ms (threshold: 2000ms) ← ANOMALOUS
service_gc_pause_ms = 600ms ← ELEVATED
service_db_connections_active = 45/50 ← NEAR MAX
```

**Watcher output:**
```json
{
  "is_incident": true,
  "confidence": 0.9,
  "severity": "critical",
  "summary": "user-service critical: memory at 92%, error rate 35%, response time 3800ms, gc pauses 600ms, db connections 45/50"
}
```

**Diagnostician reasoning (autonomous, no scenario hint):**
```
Step 1: memory_percent=92% ANOMALOUS, cpu_percent=75% ELEVATED, error_rate=0.35 ANOMALOUS
  → Pattern: HIGH MEMORY + HIGH ERRORS + ELEVATED CPU = likely memory leak or connection pool exhaustion

Step 2: search_logs("OutOfMemory", "user-service") → 12 matches
  → Found: "OutOfMemoryError: unable to allocate buffer for connection pool"
  → Found: "GC overhead limit exceeded"
  search_logs("connection pool", "user-service") → 8 matches
  → Found: "ConnectionPoolExhausted: all connections in use"

Step 3: get_deployment_history("user-service")
  → No recent restart or image change → NOT a bad deployment

Step 4: Correlate: High memory + OOM errors + connection pool exhaustion + no deployment
  → Root cause: Memory leak in connection pool — connections opened but not released
```

**Diagnostician output:**
```json
{
  "root_cause": "Memory leak in user-service connection pool. Database connections are being opened but not released, causing pool exhaustion. Memory has climbed to 92% with OOM errors in logs.",
  "confidence": 0.85,
  "evidence": ["memory at 92%", "12 OOM errors in logs", "db connections at 45/50", "no recent deployment"],
  "pattern": "memory_leak"
}
```

**Strategist plan:**
```json
{
  "actions": [
    {
      "description": "Restart user-service to clear leaked connections and free memory",
      "tool": "restart_service",
      "risk_level": "risky",
      "params": {"service": "user-service", "reason": "Memory leak - connection pool exhaustion"}
    },
    {
      "description": "Scale user-service to 2 replicas for redundancy during restart",
      "tool": "scale_service",
      "risk_level": "safe",
      "params": {"service": "user-service", "replicas": 2}
    }
  ],
  "reasoning": "Restart clears the leaked connections and frees memory. Scaling provides redundancy. Restart is RISKY because it causes brief downtime."
}
```

**Human decision:** Approve restart (RISKY), scale auto-executes (SAFE)

**Executor actions:**
```
1. scale_service("user-service", 2) → docker-compose up --scale user-service=2 [AUTO - SAFE]
2. restart_service("user-service") → docker container restart sentinel-user-service [APPROVED]
   → Waits for health check → container healthy in ~10s
   → Returns: {"status": "success", "downtime_seconds": 10.1}
```

**Watcher verification:**
```
Post-restart metrics (30s later):
  service_memory_percent = 18% ← NORMAL (was 92%)
  service_cpu_percent = 12% ← NORMAL (was 75%)
  error_rate = 0.0 ← NORMAL (was 0.35)
  response_time_ms = 85ms ← NORMAL (was 3800ms)

After 3 consecutive healthy checks → "Remediation verified: user-service healthy"
Incident → resolved
```

---

#### SCENARIO 2: CPU Spike on payment-service

**Inject:**
```
POST /chaos/cpu on payment-service
→ stress-ng --cpu 4 --timeout 60
→ Also: response times increase due to CPU contention
→ Also: structured logs: {"level":"WARN","message":"Request processing timeout: payment gateway response delayed","service":"payment-service"}
```

**What Prometheus shows:**
```
service_cpu_percent{service="payment-service"} = 95% ← ANOMALOUS
service_memory_percent{service="payment-service"} = 28% ← NORMAL
error_rate = 0.15 ← ANOMALOUS (timeouts)
response_time_ms = 4200ms ← ANOMALOUS
service_gc_pause_ms = 25ms ← NORMAL
service_db_connections_active = 8/50 ← NORMAL
```

**Diagnostician reasoning:**
```
Step 1: cpu=95% ANOMALOUS, memory=28% NORMAL, error_rate=0.15 ANOMALOUS
  → Pattern: HIGH CPU + NORMAL MEMORY = CPU exhaustion (NOT memory leak)

Step 2: search_logs("timeout", "payment-service") → 6 matches
  → Found: "Request processing timeout: payment gateway response delayed"
  search_logs("OutOfMemory", "payment-service") → 0 matches ← confirms NOT memory issue

Step 3: get_deployment_history → no recent changes

Step 4: High CPU + normal memory + timeouts + no deployment
  → Root cause: CPU exhaustion causing request timeouts
```

**Diagnostician output:**
```json
{
  "root_cause": "CPU exhaustion on payment-service. CPU at 95% causing request processing timeouts. Memory is normal at 28%, ruling out memory leak.",
  "confidence": 0.8,
  "evidence": ["cpu at 95%", "memory normal at 28%", "6 timeout errors in logs", "no recent deployment"],
  "pattern": "cpu_exhaustion"
}
```

**Strategist plan:**
```json
{
  "actions": [
    {
      "description": "Scale payment-service to 3 replicas to distribute CPU load",
      "tool": "scale_service",
      "risk_level": "safe",
      "params": {"service": "payment-service", "replicas": 3}
    },
    {
      "description": "Restart payment-service to kill any runaway processes",
      "tool": "restart_service",
      "risk_level": "risky",
      "params": {"service": "payment-service", "reason": "CPU exhaustion - potential runaway process"}
    }
  ]
}
```

**Executor:** Scale auto-executes (SAFE). Human approves restart → container restarts → CPU drops to normal.

**Watcher verification:** CPU returns to ~15%, response times normalize → remediation verified.

---

#### SCENARIO 3: Network Latency on api-gateway

**Inject:**
```
POST /chaos/latency on api-gateway
→ tc qdisc add dev eth0 root netem delay 500ms
→ All traffic through api-gateway gets 500ms added delay
→ Upstream calls to user-service and payment-service timeout
→ Logs: {"level":"ERROR","message":"UpstreamTimeout: user-service did not respond within 2000ms","service":"api-gateway"}
```

**What Prometheus shows:**
```
service_cpu_percent{service="api-gateway"} = 12% ← NORMAL
service_memory_percent{service="api-gateway"} = 20% ← NORMAL
error_rate = 0.28 ← ANOMALOUS
response_time_ms = 25400ms ← EXTREMELY ANOMALOUS
gateway_upstream_latency_seconds{upstream="user-service"} = 2.8s ← HIGH
gateway_cache_misses_total increasing ← cache misses rising
```

**Diagnostician reasoning:**
```
Step 1: cpu=12% NORMAL, memory=20% NORMAL, response_time=25400ms EXTREME, error_rate=0.28 ANOMALOUS
  → Pattern: NORMAL CPU + NORMAL MEMORY + EXTREME LATENCY = external/network issue (NOT resource exhaustion)

Step 2: search_logs("timeout", "api-gateway") → 15 matches
  → Found: "UpstreamTimeout: user-service did not respond within 2000ms"
  → Found: "UpstreamTimeout: payment-service connection timed out"
  search_logs("OutOfMemory", "api-gateway") → 0 matches
  search_logs("connection refused", "api-gateway") → 0 matches

Step 3: get_deployment_history → no recent changes

Step 4: Normal resources + extreme latency + upstream timeouts + no deployment
  → Root cause: Network issue affecting api-gateway's connections to upstream services
```

**Diagnostician output:**
```json
{
  "root_cause": "Network latency issue on api-gateway. Response times at 25s while CPU and memory are normal. Upstream services timing out. Likely network degradation or congestion.",
  "confidence": 0.75,
  "evidence": ["response time 25400ms", "cpu normal 12%", "memory normal 20%", "15 upstream timeout errors", "no recent deployment"],
  "pattern": "network_issue"
}
```

**Strategist plan:**
```json
{
  "actions": [
    {
      "description": "Scale api-gateway to 2 replicas to handle degraded throughput",
      "tool": "scale_service",
      "risk_level": "safe",
      "params": {"service": "api-gateway", "replicas": 2}
    },
    {
      "description": "Restart api-gateway to reset network connections",
      "tool": "restart_service",
      "risk_level": "risky",
      "params": {"service": "api-gateway", "reason": "Network latency - resetting connections"}
    }
  ]
}
```

**IMPORTANT NOTE:** Restart will actually fix this because when the container restarts, the tc netem rules are lost (they're in the container's network namespace). So the restart genuinely resolves the network latency. This is a realistic behavior — in production, restarting a pod often resets its network state.

**Watcher verification:** After restart, latency drops from 25s to ~85ms → verified.

---

#### SCENARIO 4: Kill Service (user-service container stopped)

**Inject:**
```
POST /chaos/inject with type="kill_service", target="user-service"
→ docker stop sentinel-user-service
→ Container goes from running to exited
→ api-gateway starts getting connection refused errors for /api/users/*
```

**What Prometheus shows:**
```
up{job="user-service"} = 0 ← SERVICE DOWN
service_cpu_percent{service="user-service"} = NaN/absent ← NO DATA
service_memory_percent{service="user-service"} = NaN/absent ← NO DATA
# api-gateway metrics:
error_rate{service="api-gateway"} = 0.50+ ← ANOMALOUS (half of requests fail, the ones going to user-service)
gateway_upstream_latency_seconds{upstream="user-service"} = NaN ← connection refused
```

**Watcher detects:**
The Watcher's quick_check for user-service gets None/NaN from Prometheus (service is down, no metrics being scraped). The `up` metric is 0. This is a special case — the Watcher should treat missing metrics + up=0 as a critical anomaly.

**Diagnostician reasoning:**
```
Step 1: All metrics for user-service are absent/NaN. up=0.
  → Pattern: SERVICE DOWN — container is not running

Step 2: search_logs("user-service") → no recent logs (container is stopped)
  → Confirms service is completely down, not just degraded

Step 3: get_container_status("user-service")
  → status: "exited", exit_code: 0 or 137
  → Container was stopped, not crashed (exit code matters)

Step 4: Service completely down + no metrics + container exited
  → Root cause: user-service container is down
```

**Diagnostician output:**
```json
{
  "root_cause": "user-service container is down. Container status is 'exited'. No metrics or logs being produced. All dependent services affected.",
  "confidence": 0.95,
  "evidence": ["up=0", "container status: exited", "no metrics available", "api-gateway errors rising"],
  "pattern": "service_down"
}
```

**Strategist plan:**
```json
{
  "actions": [
    {
      "description": "Restart user-service to bring it back online",
      "tool": "restart_service",
      "risk_level": "risky",
      "params": {"service": "user-service", "reason": "Service is down - container exited"}
    }
  ]
}
```

Note: restart_service on a stopped container should use `container.start()` not `container.restart()`. The infra_server.py code should handle both cases:
```python
if container.status == "exited":
    container.start()
else:
    container.restart(timeout=10)
```

**Watcher verification:** After start, up=1, metrics resume, error rates normalize → verified.

---

#### SCENARIO 5: Cache Failure (Redis stopped)

**Inject:**
```
POST /chaos/inject with type="cache_failure"
→ docker stop sentinel-redis
→ All 3 services lose their cache layer
→ api-gateway: cache misses go to 100%, latency increases
→ payment-service: payment status cache gone, DB queries increase
→ user-service: session cache gone
```

**What Prometheus shows:**
```
# All 3 services affected simultaneously:
response_time_ms{service="api-gateway"} = 8500ms ← ANOMALOUS
response_time_ms{service="payment-service"} = 3200ms ← ANOMALOUS
response_time_ms{service="user-service"} = 1800ms ← ELEVATED
error_rate{service="api-gateway"} = 0.20 ← ANOMALOUS
error_rate{service="payment-service"} = 0.12 ← ANOMALOUS
# CPU and memory mostly normal across all services
gateway_cache_misses_total increasing rapidly
gateway_cache_hits_total = 0 (flat)
```

**Watcher detects:** Multiple services anomalous simultaneously. This is a key signal — when all services degrade at once, it's likely a shared dependency (Redis or PostgreSQL).

**Diagnostician reasoning:**
```
Step 1: Multiple services degraded. Response times high across all. CPU/memory normal.
  → Pattern: MULTI-SERVICE DEGRADATION + NORMAL RESOURCES = shared dependency failure

Step 2: search_logs("redis", "api-gateway") → matches: "Redis connection refused"
  search_logs("cache", "api-gateway") → matches: "CacheConnectionError: unable to connect to Redis"
  search_logs("redis", "payment-service") → matches: "Redis connection timeout"

Step 3: get_container_status("redis") → status: "exited"
  → Redis is DOWN

Step 4: Multiple services degraded + Redis down + cache errors in logs
  → Root cause: Redis cache failure — all cache-dependent services affected
```

**Diagnostician output:**
```json
{
  "root_cause": "Redis cache failure. Redis container is down, causing cache misses and connection errors across all services. api-gateway, payment-service, and user-service all affected.",
  "confidence": 0.9,
  "evidence": ["Redis container exited", "cache connection errors in all service logs", "all services degraded simultaneously", "cpu/memory normal"],
  "pattern": "cache_failure"
}
```

**Strategist plan:**
```json
{
  "actions": [
    {
      "description": "Restart Redis to restore cache service",
      "tool": "restart_service",
      "risk_level": "risky",
      "params": {"service": "redis", "reason": "Redis is down - all cache-dependent services affected"}
    },
    {
      "description": "Flush Redis cache after restart to ensure clean state",
      "tool": "flush_cache",
      "risk_level": "safe",
      "params": {}
    }
  ]
}
```

Note: restart_service must handle Redis (not just our 3 services). The infra_server.py container lookup should use `sentinel-redis` for Redis.

**Watcher verification:** After Redis restarts, response times across all services normalize → verified. The Watcher should check all 3 services, not just one.

---

### Scenarios We Are NOT Doing (and why)

```
❌ rollback_deployment — We don't have multiple image versions in our Docker setup.
   No CI/CD pipeline, no image registry with version tags. Remove all rollback code.

❌ update_config — Our toy services don't have external config files that can be
   hot-reloaded. Remove all config update code.

❌ bad_deployment — Without rollback capability, we can't meaningfully remediate this.
   The Diagnostician can still DETECT a bad deployment pattern (errors after restart),
   but the fix would just be "restart again" which doesn't solve a code bug.
   Remove this as a fault injection type.

❌ disk_full — Our toy services don't use local disk significantly.
   Not meaningful in this setup.

❌ packet_loss — Similar effect to network latency, adds complexity without
   demonstrating a different agent decision path. Remove to keep it clean.
```

### Final Fault Injection List (exactly 5)

```
1. memory_leak      → Target: any service    → Fix: restart + scale
2. cpu_spike        → Target: any service    → Fix: scale + restart
3. network_latency  → Target: any service    → Fix: restart (resets tc rules) + scale
4. kill_service     → Target: any service    → Fix: restart (start stopped container)
5. cache_failure    → Target: redis          → Fix: restart redis + flush cache
```

### Agent Tools We Actually Need (only these)

```
Watcher tools:
  get_current_metrics(service)    → Prometheus query
  get_metric_history(service, metric) → Prometheus range query
  detect_anomaly(service, metric) → Compare against threshold
  get_recent_errors(service)      → Loki query

Diagnostician tools:
  search_logs(query, service)     → Loki query
  detect_anomaly(service, metric) → Prometheus query
  get_deployment_history(service) → Docker API (container info)
  get_container_status(service)   → Docker API (check if running)

Strategist tools:
  send_notification(channel, message) → Create audit log entry

Executor tools:
  restart_service(service, reason)  → docker container restart/start
  scale_service(service, replicas)  → docker-compose scale
  flush_cache()                     → redis-cli FLUSHALL
```

### Diagnostic Decision Tree (embedded in Diagnostician prompt)

```
METRIC PATTERN                           → DIAGNOSIS PATTERN    → PRIMARY FIX
─────────────────────────────────────────────────────────────────────────────
High memory + high CPU + high errors     → memory_leak          → restart + scale
High CPU + normal memory + timeouts      → cpu_exhaustion       → scale + restart
Normal CPU + normal memory + extreme     → network_issue        → restart + scale
  latency + upstream timeouts
Service down (up=0, no metrics)          → service_down         → restart
Multiple services degraded + normal      → cache_failure        → restart redis
  resources + Redis connection errors                             + flush cache
```

---

## GAPS IDENTIFIED AND FIXES (apply throughout implementation)

The following gaps were found during line-by-line review. Apply these fixes when implementing the corresponding sections.

### Gap A: Chaos endpoint must simulate cascading metric effects
**Where:** Step 1.1, user-service chaos/memory endpoint
**Issue:** The doc says "background task inflates db_connections_active and gc_pause_ms" but the service code doesn't specify how.
**Fix:** When `/chaos/memory` is called, start an asyncio background task that:
```python
async def simulate_cascading_effects():
    """Gradually inflate simulated gauges to mimic real memory leak effects."""
    while _chaos_active:
        mem = psutil.virtual_memory().percent
        if mem > 70:
            # Simulated: connection pool fills as memory pressure increases
            DB_CONN_ACTIVE.labels(service=SERVICE).set(min(50, int(mem * 0.5)))
            GC_GAUGE.labels(service=SERVICE).set(min(1000, mem * 7))  # GC pauses increase with memory
        await asyncio.sleep(2)
```
Start this task in `/chaos/memory` and stop it in `/chaos/stop`. Use a module-level `_chaos_active` flag.

### Gap B: Error logs must be structured JSON to stdout
**Where:** Step 1.1, service behavior under chaos
**Issue:** Need to explicitly implement structured error logging.
**Fix:** In each service, use Python's `logging` with a JSON formatter:
```python
import logging, json
class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "service": SERVICE,
            "message": record.getMessage(),
        })
logger = logging.getLogger(SERVICE)
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
```
Then in business endpoints under chaos: `logger.error("OutOfMemoryError: unable to allocate buffer for connection pool")`

### Gap C: get_deployment_history must distinguish restart from deployment
**Where:** Scenario 1 Diagnostician, infra_server.py
**Issue:** After a previous restart, `restart_count > 0` and `started_at` is recent. Diagnostician might confuse this with a deployment.
**Fix:** `get_deployment_history` should always return `recent_deploy: False` and include context:
```python
def get_deployment_history(service):
    container = client.containers.get(f"sentinel-{service}")
    return {
        "current_image": container.image.tags[0] if container.image.tags else "unknown",
        "started_at": container.attrs["State"]["StartedAt"],
        "restart_count": container.attrs["RestartCount"],
        "status": container.status,
        "recent_deploy": False,  # Single-version setup, restarts are NOT deployments
        "note": "This infrastructure uses single-version containers. Restarts do not indicate code deployments."
    }
```
Also add to Diagnostician prompt: "Note: In this infrastructure, get_deployment_history returning a recent started_at with recent_deploy=False means the service was restarted (not redeployed). A restart is a remediation action, not a new code version."

### Gap D: Scale-down after incident resolution
**Where:** Scenario 1 post-resolution
**Issue:** After scale_service("user-service", 2), we have 2 replicas. After incident resolves, we should scale back to 1.
**Fix:** In verify_remediation(), after confirming healthy, scale back:
```python
if healthy_count >= VERIFICATION_CHECKS:
    # If service was scaled up during remediation, scale back to 1
    # Check current replica count
    containers = client.containers.list(filters={"name": f"sentinel-{service}"})
    if len(containers) > 1:
        logger.info(f"Scaling {service} back to 1 replica after verified remediation")
        subprocess.run(["docker-compose", "up", "-d", "--scale", f"{service}=1"], check=False)
```

### Gap E: Docker restart policy must be explicit
**Where:** docker-compose.yml
**Issue:** Without explicit restart policy, default is `no` which is correct for our chaos scenarios. But should be explicit.
**Fix:** Add `restart: "no"` to all 3 microservice definitions in docker-compose.yml. This ensures Docker doesn't auto-restart containers we intentionally stop.

### Gap F: flush_cache ordering with restart
**Where:** Scenario 5, Strategist actions
**Issue:** flush_cache is SAFE (auto-execute) but restart_redis is RISKY (needs approval). If flush auto-executes before Redis is restarted, it will fail (Redis is down).
**Fix:** Change the execution model: SAFE actions that depend on a RISKY action being completed first should NOT auto-execute independently. Instead:
- Option 1: Make flush_cache part of the Executor flow — after restart_redis succeeds, Executor also runs flush_cache as a post-step.
- Option 2: The Strategist should mark flush_cache as risk_level="risky" so it goes through approval too, ordered after restart.
- **Recommended: Option 1.** In the Executor, after successfully restarting Redis:
```python
if service == "redis" and action_tool == "restart_service":
    # Post-restart: flush cache for clean state
    flush_result = flush_cache()
    log_audit("executor", "flush_cache", "post_restart_cleanup", flush_result)
```
Remove flush_cache as a separate Strategist action for cache_failure. The Strategist only proposes restart_redis.

### Gap G: alert_server.py must be kept
**Where:** Step 4 (MCP servers), Watcher tools
**Issue:** The Watcher calls `create_incident_ticket()` and `send_notification()` which are in alert_server.py. The doc focuses on modifying metrics_server, logs_server, and infra_server but never mentions alert_server.py.
**Fix:** Keep `mcp_servers/alert_server.py` as-is. These tools write to PostgreSQL (create Incident rows, create AuditLog entries) which doesn't change with live data. Add this note to Step 4: "alert_server.py — NO CHANGES. create_incident_ticket() and send_notification() write to PostgreSQL and work the same with live or mock data."

### Gap H: chaos_server.py is redundant
**Where:** Step 4.4
**Issue:** The backend `/api/chaos/inject` endpoint calls service HTTP endpoints directly. A separate MCP server for chaos is unnecessary overhead.
**Fix:** Remove `mcp_servers/chaos_server.py` from the file list. Chaos injection is handled entirely by `backend/dashboard_api.py` calling service `/chaos/*` endpoints via httpx. The chaos endpoints live IN the toy services, not as an MCP server.

### Gap I: Watcher LLM prompt should receive pre-fetched metrics
**Where:** Step 5.1, Watcher prompt
**Issue:** The prompt says "Call get_current_metrics(service)" but the watcher_loop already has the metrics from check_anomalies(). Calling again wastes an LLM tool call.
**Fix:** Update the Watcher prompt to include the metrics in context:
```
You are a Watcher agent. An anomaly has been detected on {service}.

Current metrics (from Prometheus, just captured):
{json.dumps(trigger_metrics, indent=2)}

These metrics triggered the anomaly alert. Your job is to:
1. Call get_metric_history(service, metric) for the anomalous metrics to understand trends
2. Call get_recent_errors(service) to check for error patterns in logs
3. Based on ALL data, confirm this is a real incident (not a transient spike)
...
```
This way the LLM starts with metrics already in context and only needs 2-3 additional tool calls (history + errors + create ticket), not 6.

### Gap J: Exception handling in async pipeline tasks
**Where:** Cross-cutting, watcher_loop
**Issue:** `asyncio.create_task(run_full_pipeline(...))` silently swallows exceptions.
**Fix:** Wrap in safe handler:
```python
async def safe_run_pipeline(service, anomaly):
    try:
        await run_full_pipeline(service, anomaly)
    except Exception as e:
        logger.error(f"Pipeline failed for {service}: {e}", exc_info=True)
    finally:
        _pipeline_running.discard(service)

asyncio.create_task(safe_run_pipeline(service, anomaly))
```

### Gap K: Evaluation results vs test fixtures
**Where:** Step 10 cleanup
**Issue:** Doc says delete `tests/fixtures/` files. But `evaluation/results/` JSON files (eval_*.json, safety_report_*.json) are evaluation outputs, NOT fixtures. They should be kept — the Evaluations and Safety pages read them.
**Fix:** Clarify in Step 10:
- DELETE: `tests/fixtures/memory_leak.json`, `tests/fixtures/bad_deployment.json`, `tests/fixtures/api_timeout.json`, `tests/fixtures/_summary.json`
- KEEP: `evaluation/results/eval_*.json`, `evaluation/results/safety_report_*.json`
- The eval pipeline and safety runner can still be run separately to generate these files. They are independent of the live data system.

### Gap L: Docker client initialization
**Where:** Step 7.1, dashboard_api.py chaos endpoint
**Issue:** `docker.from_env()` called inside request handler creates a new client per request.
**Fix:** Create Docker client once at module level:
```python
# At top of dashboard_api.py or in a shared module:
import docker
_docker_client = None
def get_docker_client():
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client
```

### Gap M: Test for concurrent fault injection
**Where:** Step 11 testing
**Issue:** No test for injecting a fault while another incident is active.
**Fix:** Add test scenario:
```
Test 6: Concurrent faults
  - Inject memory_leak on user-service
  - While incident is active, inject cpu_spike on payment-service  
  - Verify: two separate incidents created (one per service)
  - Verify: api-gateway does NOT get a separate incident (cascading dedup)
  - Approve both restarts → both resolve independently
```

### 1.1 Create `services/user-service/`

Create `services/user-service/app.py` — a FastAPI microservice that:

- Runs on port 8001
- Has business endpoints: `GET /health`, `GET /users`, `POST /users`
- Exposes `GET /metrics` in Prometheus text format using `prometheus_client` library
- Has a background task that updates CPU/memory gauges from `psutil` every 5 seconds
- Has chaos endpoints: `POST /chaos/memory`, `POST /chaos/cpu`, `POST /chaos/latency`, `POST /chaos/stop`
- Under chaos (memory > 85%), business endpoints start returning 500 errors with realistic error messages like "OutOfMemoryError: unable to allocate buffer", "ConnectionPoolExhausted: all connections in use", "GC overhead limit exceeded"
- Logs structured JSON to stdout: `{"timestamp": "...", "level": "ERROR", "service": "user-service", "message": "...", "trace_id": "..."}`
- Has a background traffic generator task that calls its own endpoints every 1-3 seconds so Prometheus always has rate() data

**Prometheus metrics to expose:**

```python
# Gauges — updated every 5s from psutil
service_cpu_percent{service="user-service"}          # psutil.cpu_percent()
service_memory_percent{service="user-service"}       # psutil.virtual_memory().percent
service_gc_pause_ms{service="user-service"}          # simulated, increases under memory pressure
service_db_connections_active{service="user-service"} # simulated, climbs during memory leak
service_db_connections_max{service="user-service"}    # fixed at 50

# Histogram — recorded on every request
http_request_duration_seconds{service="user-service", method="GET", endpoint="/users", status="200"}
  buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]

# Counter — incremented on every request
http_requests_total{service="user-service", method="GET", status="200"}
http_requests_total{service="user-service", method="POST", status="500"}
```

**Chaos injection endpoints:**

```python
POST /chaos/memory?percent=90&duration=120
  → subprocess.Popen(["stress-ng", "--vm", "1", "--vm-bytes", "90%", "--timeout", "120"])
  → Also: start a background task that artificially inflates db_connections_active gauge
    and increases gc_pause_ms gauge to simulate cascading effects of a memory leak

POST /chaos/cpu?cores=4&duration=60
  → subprocess.Popen(["stress-ng", "--cpu", "4", "--timeout", "60"])

POST /chaos/latency?delay_ms=500&duration=120
  → subprocess.run(["tc", "qdisc", "add", "dev", "eth0", "root", "netem", "delay", "500ms"])
  → Schedule removal after duration

POST /chaos/stop
  → pkill stress-ng, remove tc rules, reset simulated gauges to normal
```

**Key behavior under chaos — the service must produce realistic symptoms:**

When memory chaos is active:
- `service_memory_percent` climbs to 85%+ (from psutil, real)
- `service_gc_pause_ms` increases to 500ms+ (simulated, correlated with memory)
- `service_db_connections_active` climbs toward max (simulated, connection pool exhaustion)
- `POST /users` returns 500 with "OutOfMemoryError" about 30-50% of the time
- `http_request_duration_seconds` increases (real, due to CPU contention from stress-ng)
- Structured error logs are written to stdout (picked up by Promtail → Loki)

When CPU chaos is active:
- `service_cpu_percent` goes to 80-100% (from psutil, real)
- Response times increase (real)
- Memory stays normal (key differentiator for Diagnostician)

When latency chaos is active:
- `http_request_duration_seconds` spikes dramatically (real, from tc netem)
- CPU and memory stay normal (key differentiator — it's a network issue)
- Error rate increases as upstream callers timeout

Create `services/user-service/Dockerfile`:
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    stress-ng iproute2 curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
```

Create `services/user-service/requirements.txt`:
```
fastapi==0.115.0
uvicorn==0.30.0
psutil==6.0.0
prometheus_client==0.21.0
httpx==0.27.0
```

### 1.2 Create `services/payment-service/`

Same pattern as user-service but on port 8002 with:
- Business endpoints: `GET /health`, `POST /payments`, `GET /payments/{id}`
- Connects to Redis (for caching payment status)
- Under chaos, produces different error messages: "PaymentGatewayTimeout", "StripeConnectionRefused", "DatabaseConnectionPoolExhausted"
- Logs reference payment-specific context: transaction IDs, payment amounts, gateway errors
- Same chaos endpoints and Prometheus metrics with `service="payment-service"`
- Same traffic generator

### 1.3 Create `services/api-gateway/`

Same pattern on port 8003 but acts as a gateway:
- Business endpoints: `GET /health`, proxies `GET /api/users/*` → user-service, `GET /api/payments/*` → payment-service
- Connects to Redis for response caching
- Additional Prometheus metrics:
  ```python
  gateway_upstream_latency_seconds{service="api-gateway", upstream="user-service"}
  gateway_cache_hits_total{service="api-gateway"}
  gateway_cache_misses_total{service="api-gateway"}
  ```
- Under chaos, produces: "UpstreamTimeout", "CircuitBreakerOpen", "CacheConnectionError"
- When Redis is stopped externally, cache_misses spike and latency increases dramatically
- Same traffic generator calling its own proxy endpoints

---

## STEP 2: Observability Stack

### 2.1 Create `monitoring/prometheus/prometheus.yml`

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - 'alert_rules.yml'

scrape_configs:
  - job_name: 'user-service'
    static_configs:
      - targets: ['user-service:8001']
    metrics_path: /metrics
    scrape_interval: 10s

  - job_name: 'payment-service'
    static_configs:
      - targets: ['payment-service:8002']
    metrics_path: /metrics
    scrape_interval: 10s

  - job_name: 'api-gateway'
    static_configs:
      - targets: ['api-gateway:8003']
    metrics_path: /metrics
    scrape_interval: 10s

  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
```

### 2.2 Create `monitoring/prometheus/alert_rules.yml`

```yaml
groups:
  - name: sentinel_alerts
    rules:
      - alert: HighMemory
        expr: service_memory_percent > 85
        for: 30s
        labels:
          severity: critical
      - alert: HighCPU
        expr: service_cpu_percent > 80
        for: 30s
        labels:
          severity: warning
      - alert: HighErrorRate
        expr: sum by(service)(rate(http_requests_total{status=~"5.."}[2m])) / sum by(service)(rate(http_requests_total[2m])) > 0.10
        for: 30s
        labels:
          severity: critical
      - alert: HighLatency
        expr: histogram_quantile(0.95, sum by(le, service)(rate(http_request_duration_seconds_bucket[2m]))) > 2.0
        for: 30s
        labels:
          severity: warning
      - alert: ServiceDown
        expr: up == 0
        for: 15s
        labels:
          severity: critical
```

### 2.3 Create `monitoring/loki/loki-config.yml`

```yaml
auth_enabled: false
server:
  http_listen_port: 3100
common:
  ring:
    instance_addr: 127.0.0.1
    kvstore:
      store: inmemory
  replication_factor: 1
  path_prefix: /loki
schema_config:
  configs:
    - from: 2020-10-24
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h
storage_config:
  filesystem:
    directory: /loki/chunks
```

### 2.4 Create `monitoring/promtail/promtail-config.yml`

```yaml
server:
  http_listen_port: 9080
positions:
  filename: /tmp/positions.yaml
clients:
  - url: http://loki:3100/loki/api/v1/push
scrape_configs:
  - job_name: docker
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 5s
    relabel_configs:
      - source_labels: ['__meta_docker_container_name']
        regex: '/?(.*)'
        target_label: 'container'
      - source_labels: ['__meta_docker_container_name']
        regex: '/?sentinel-(.*)'
        target_label: 'service'
```

### 2.5 Create `monitoring/grafana/provisioning/datasources/datasources.yml`

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true
  - name: Loki
    type: loki
    url: http://loki:3100
```

---

## STEP 3: Backend — Prometheus Client Module

### 3.1 Create `backend/prometheus_client.py`

This is the core module that replaces all fixture reads with live Prometheus queries. Create it with these functions:

```python
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
LOKI_URL = os.getenv("LOKI_URL", "http://loki:3100")

SERVICES = ["user-service", "payment-service", "api-gateway"]

THRESHOLDS = {
    "memory_percent": 85.0,
    "cpu_percent": 80.0,
    "error_rate": 0.10,         # 10%
    "response_time_ms": 2000.0, # 2 seconds
}
```

**Functions needed:**

`async def prom_query(query: str) -> Optional[float]` — instant PromQL query, returns scalar value or None.

`async def prom_range_query(query: str, minutes_back: int = 60, step: str = "15s") -> list[tuple[float, float]]` — range query, returns list of (timestamp, value) pairs. Compute start/end from current time.

`async def get_service_health(service: str) -> dict` — queries all 4 key metrics for a service via PromQL and returns a dict matching the existing `ServiceHealthResponse` shape:
```python
{
    "service": service,
    "status": "healthy" | "critical" | "unknown",
    "cpu_percent": float,
    "memory_percent": float,
    "response_time_ms": float,
    "error_rate": float,
}
```

PromQL queries for each field:
- `cpu_percent` → `service_cpu_percent{service="$SVC"}`
- `memory_percent` → `service_memory_percent{service="$SVC"}`
- `response_time_ms` → `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{service="$SVC"}[2m])) * 1000`
- `error_rate` → `sum(rate(http_requests_total{service="$SVC",status=~"5.."}[2m])) / sum(rate(http_requests_total{service="$SVC"}[2m]))`
- `status` → based on `up{job="$SVC"}` plus whether any metric exceeds critical threshold

`async def get_all_services_health() -> list[dict]` — calls `get_service_health` for each service.

`async def check_anomalies(service: str) -> Optional[dict]` — compares all metrics against thresholds, returns None if healthy, or:
```python
{
    "service": service,
    "anomalies": [
        {"metric": "memory_percent", "value": 99.5, "threshold": 85.0, "severity": "critical"},
        ...
    ],
    "worst_severity": "critical",
    "detection_metrics": { full health dict },
}
```

`async def get_metric_history(service: str, metric: str, minutes: int = 60) -> dict` — returns trend data:
```python
{
    "data_points": int,
    "trend": "increasing" | "decreasing" | "stable" | "oscillating",
    "values": [(timestamp, value), ...],
    "min": float, "max": float, "avg": float,
}
```
Trend calculation: compare average of first 25% of values vs last 25%. If last > first * 1.2 → "increasing", etc.

`async def query_loki(query: str, service: str, minutes: int = 10) -> list[dict]` — queries Loki for logs:
```python
logql = f'{{container=~"sentinel-{service}.*"}} |= "{query}"'
# Query Loki HTTP API: GET /loki/api/v1/query_range
# Return list of log entries with timestamp, message, level
```

`async def get_deployment_info(service: str) -> dict` — uses Docker API to get container info:
```python
import docker
client = docker.from_env()
container = client.containers.get(f"sentinel-{service}")
return {
    "current_image": container.image.tags[0] if container.image.tags else "unknown",
    "started_at": container.attrs["State"]["StartedAt"],
    "restart_count": container.attrs["RestartCount"],
    "status": container.status,
}
```

---

## STEP 4: Modify MCP Servers for Live Data

### 4.1 Modify `mcp_servers/metrics_server.py`

**Remove** all fixture/scenario-based logic. Every tool function now queries Prometheus.

Remove the `scenario` parameter from all functions. The tools should be:

`get_current_metrics(service: str)` → calls `backend.prometheus_client.get_service_health(service)` and returns the result. No scenario parameter.

`get_metric_history(service: str, metric: str, minutes: int = 60)` → calls `backend.prometheus_client.get_metric_history(service, metric, minutes)`. No scenario parameter.

`detect_anomaly(service: str, metric: str)` → queries current value from Prometheus, compares against threshold, returns:
```python
{
    "anomalous": bool,
    "severity": "critical" | "warning" | "normal",
    "current_value": float,
    "threshold": float,
    "metric": metric,
}
```

`get_recent_errors(service: str, minutes: int = 10)` → calls `backend.prometheus_client.query_loki("error", service, minutes)`. Returns error count and log entries.

### 4.2 Modify `mcp_servers/logs_server.py`

**Remove** all fixture-based logic. Every tool now queries Loki.

`search_logs(query: str, service: str, minutes: int = 10)` → calls `backend.prometheus_client.query_loki(query, service, minutes)`. Returns:
```python
{
    "matches": int,
    "query": query,
    "service": service,
    "logs": [{"timestamp": "...", "message": "...", "level": "..."}, ...]
}
```

`get_recent_errors(service: str, minutes: int = 10)` → same as above but with query="error|ERROR|Exception|FATAL"

### 4.3 Modify `mcp_servers/infra_server.py`

**Remove** all mock returns. Every tool now uses Docker API.

```python
import docker
client = docker.from_env()
```

`restart_service(service: str, reason: str = "")`:
```python
container = client.containers.get(f"sentinel-{service}")
start = time.time()
container.restart(timeout=10)
# Wait for healthy
for _ in range(30):
    container.reload()
    if container.status == "running":
        # Check health endpoint
        try:
            resp = httpx.get(f"http://{service}:{PORT}/health", timeout=5)
            if resp.status_code == 200:
                break
        except:
            pass
    time.sleep(1)
downtime = time.time() - start
return {"status": "success", "action": "restart", "service": service, "downtime_seconds": round(downtime, 1), "reason": reason}
```

`scale_service(service: str, replicas: int, reason: str = "")`:
```python
subprocess.run(["docker-compose", "up", "-d", "--scale", f"{service}={replicas}", "--no-recreate"], check=True)
return {"status": "success", "action": "scale", "service": service, "replicas": replicas, "reason": reason}
```

`rollback_deployment(service: str, target_version: str)`:
```python
container = client.containers.get(f"sentinel-{service}")
current_image = container.image.tags[0] if container.image.tags else "unknown"
container.stop()
container.remove()
# Recreate with different image tag
client.containers.run(
    f"sentinel-{service}:{target_version}",
    detach=True, name=f"sentinel-{service}",
    network="sentinel-net",
    # ... same env/ports as docker-compose
)
return {"status": "success", "action": "rollback", "from": current_image, "to": target_version}
```

`get_deployment_history(service: str)`:
```python
return backend.prometheus_client.get_deployment_info(service)
```

`get_container_status(service: str)`:
```python
container = client.containers.get(f"sentinel-{service}")
return {
    "status": container.status,
    "health": container.health if hasattr(container, 'health') else "unknown",
    "started_at": container.attrs["State"]["StartedAt"],
    "restart_count": container.attrs["RestartCount"],
    "image": container.image.tags[0] if container.image.tags else "unknown",
}
```

`flush_cache()`:
```python
redis_container = client.containers.get("sentinel-redis")
result = redis_container.exec_run("redis-cli FLUSHALL")
return {"status": "success", "action": "cache_flushed", "output": result.output.decode()}
```

### 4.4 Create `mcp_servers/chaos_server.py` (NEW)

New MCP server for fault injection. The backend `/api/chaos/inject` endpoint calls these.

`inject_memory_leak(service: str, percent: int = 90, duration: int = 120)`:
```python
container = client.containers.get(f"sentinel-{service}")
container.exec_run(
    f"stress-ng --vm 1 --vm-bytes {percent}% --timeout {duration}",
    detach=True
)
return {"status": "injecting", "fault": "memory_leak", "target": service, "intensity": f"{percent}%", "duration": f"{duration}s"}
```

`inject_cpu_spike(service: str, cores: int = 4, duration: int = 60)` — same pattern with `stress-ng --cpu`

`inject_network_latency(service: str, delay_ms: int = 500, duration: int = 120)` — uses `tc qdisc add dev eth0 root netem delay`

`inject_packet_loss(service: str, loss_percent: int = 30, duration: int = 120)` — uses `tc qdisc add dev eth0 root netem loss`

`stop_dependency(dependency: str)` — `client.containers.get(f"sentinel-{dependency}").stop()`

`stop_chaos(service: str)` — kills stress-ng, removes tc rules via `exec_run`

---

## STEP 5: Agent Prompt Adaptation (GAP 1 — CRITICAL)

This is the most important change. The agents must work WITHOUT scenario hints.

### 5.1 Modify `agents/watcher.py`

**Remove** all references to `scenario` parameter.

The Watcher's LLM system prompt must change from scenario-aware to metric-aware:

**CURRENT prompt pattern (remove this):**
```
You are analyzing the {scenario} scenario for {service}...
```

**NEW prompt (use this):**
```
You are a Watcher agent for SentinelAI, monitoring live infrastructure.

You have access to real-time metrics from Prometheus and logs from Loki for the service: {service}.

Your job:
1. Call get_current_metrics(service) to get live CPU, memory, response time, error rate
2. Call get_metric_history(service, metric) for any metric that looks abnormal to understand the trend
3. Call detect_anomaly(service, metric) for each metric to confirm whether it's anomalous
4. Call get_recent_errors(service) to check for error patterns in logs
5. Based on ALL the data, decide if this is a real incident or a transient spike

If you determine this is an incident:
- Call create_incident_ticket() to create a new incident
- Call send_notification() to alert the ops team
- Return is_incident=true with a summary, severity (warning/critical), and confidence (0-1)

If the metrics are slightly elevated but not clearly problematic, return is_incident=false.

Important: You do NOT know what type of incident this is. You only see raw metrics and logs. 
Do not assume a cause — that's the Diagnostician's job.
Describe what you observe factually: "memory at 99.5%, error rate at 12.4%, response time at 3866ms"
```

The Watcher function signature changes:
```python
# BEFORE:
async def run_watcher(service: str, scenario: str) -> dict

# AFTER:
async def run_watcher_analysis(service: str, trigger_metrics: dict) -> dict
```

Where `trigger_metrics` is the dict from `check_anomalies()` containing the actual Prometheus values that triggered the alert.

### 5.2 Modify `agents/diagnostician.py` (GAP 2 — CRITICAL)

**Remove** all references to `scenario` parameter.

The Diagnostician must autonomously decide what to investigate. This is the key intelligence.

**NEW prompt:**
```
You are a Diagnostician agent for SentinelAI. The Watcher has detected an anomaly on {service}.

Here is what the Watcher observed:
{watcher_summary}

Detection metrics snapshot:
{detection_metrics_json}

Your job is to determine the ROOT CAUSE. You have these tools:

1. search_logs(query, service) — Search Loki logs. YOU decide what to search for.
2. detect_anomaly(service, metric) — Check if a specific metric is anomalous.
3. get_deployment_history(service) — Check if there was a recent deployment.
4. get_metric_history(service, metric) — Get trend data for a metric.

DIAGNOSTIC STRATEGY — follow this decision tree:

Step 1: Check which metrics are anomalous
  - If memory is high but CPU is normal → likely memory leak or connection pool issue
  - If CPU is high but memory is normal → likely compute-bound issue or infinite loop
  - If response_time is high but CPU and memory are normal → likely external dependency issue (network, cache, DB)
  - If error_rate is high → check logs for error patterns

Step 2: Based on the pattern, search logs for relevant terms:
  - High memory → search for: "OutOfMemory", "gc", "heap", "connection pool", "leak"
  - High CPU → search for: "timeout", "infinite", "loop", "deadlock", "thread"
  - High latency + normal resources → search for: "timeout", "connection refused", "redis", "cache miss", "upstream"
  - High error rate → search for: "error", "exception", "500", "failed"

Step 3: Check deployment history
  - If there was a recent deployment AND error_rate spiked → likely bad deployment
  - If no recent deployment → likely infrastructure or resource issue

Step 4: Correlate all findings into a root cause diagnosis with confidence level.

Return your diagnosis as:
{
  "root_cause": "description of what's wrong and why",
  "confidence": 0.0-1.0,
  "evidence": ["list of findings that support this conclusion"],
  "pattern": "memory_leak | bad_deployment | cache_failure | network_issue | cpu_exhaustion | dependency_failure | unknown"
}
```

The Diagnostician function signature changes:
```python
# BEFORE:
async def run_diagnostician(service: str, scenario: str, incident_id: str, watcher_result: dict) -> dict

# AFTER:
async def run_diagnostician(service: str, incident_id: str, watcher_result: dict) -> dict
```

### 5.3 Modify `agents/strategist.py`

**Remove** all references to `scenario` parameter. **Remove** rollback_deployment and update_config from available actions.

**NEW prompt:**
```
You are a Strategist agent for SentinelAI. You create remediation action plans.

Service: {service}
Watcher summary: {watcher_summary}
Diagnostician diagnosis: {diagnosis}
Root cause pattern: {diagnosis_pattern}

Based on the diagnosis, create an action plan. You have EXACTLY these tools:

SAFE actions (auto-execute, no approval needed):
- scale_service(service, replicas) — add more container replicas to distribute load
- flush_cache() — clear Redis cache to ensure clean state
- send_notification(channel, message) — notify ops team

RISKY actions (need human approval):
- restart_service(service, reason) — restart the container (brief downtime, clears memory/connections/network state)

RULES:
1. Always include at least one notification (SAFE)
2. Match the fix to the root cause pattern:
   - memory_leak → restart (RISKY) to clear leaked memory + scale (SAFE) for redundancy
   - cpu_exhaustion → scale (SAFE) to distribute load + restart (RISKY) to kill runaway processes
   - network_issue → restart (RISKY) to reset network state + scale (SAFE) for throughput
   - service_down → restart (RISKY) to bring the service back online
   - cache_failure → restart redis (RISKY) to restore cache + flush_cache (SAFE) for clean state
3. RISKY actions require human approval — register them as pending approvals
4. SAFE actions can auto-execute immediately
5. Do NOT suggest rollback_deployment or update_config — we don't have those capabilities

Return:
{
  "actions": [
    {"description": "...", "tool": "restart_service", "risk_level": "risky", "params": {...}},
    {"description": "...", "tool": "scale_service", "risk_level": "safe", "params": {...}},
  ],
  "reasoning": "why these actions address the root cause"
}
```

Function signature change:
```python
# BEFORE:
async def run_strategist(service: str, scenario: str, ...) -> dict

# AFTER: 
async def run_strategist(service: str, incident_id: str, watcher_result: dict, diagnosis: dict) -> dict
```

### 5.4 Modify `agents/executor_crew.py`

The Executor's CrewAI task must call real Docker-backed MCP tools.

Update the CrewAI tool definitions to use the real `infra_server.py` functions that now call Docker API. The Executor should:

1. Receive the approved action (tool name + params) from the approval flow
2. Call the corresponding MCP tool (which now does real Docker operations)
3. Wait for the action to complete
4. Verify the action succeeded by checking container health
5. Return the result

**IMPORTANT**: After the Executor runs, it should also call `get_current_metrics(service)` to capture a post-remediation metrics snapshot. This is used by the Watcher verification loop (Step 6).

---

## STEP 6: Watcher Loop with Auto-Detection and Verification (GAP 5)

### 6.1 Create `agents/watcher_loop.py`

This is the always-on monitoring loop that replaces "Run Scenario."

```python
POLL_INTERVAL = int(os.getenv("WATCHER_POLL_INTERVAL", "30"))  # seconds
INITIAL_DELAY = 60  # wait for Prometheus to have data after startup
CONSECUTIVE_THRESHOLD = 2  # require N consecutive anomalous checks before alerting
VERIFICATION_CHECKS = 3  # after remediation, require N healthy checks before closing
```

**Main loop logic:**

```
Every POLL_INTERVAL seconds, for each service:

1. Query check_anomalies(service) from Prometheus

2. If anomaly detected:
   - Increment anomaly_streak[service]
   - If streak >= CONSECUTIVE_THRESHOLD:
     - Check if open incident exists for this service → skip if yes
     - TRIGGER full pipeline: run_watcher_analysis → run_diagnostician → run_strategist
     - Reset streak

3. If no anomaly:
   - Reset anomaly_streak[service] to 0
   - Check if there's a recently RESOLVED incident for this service
   - If yes, increment healthy_streak[service]
   - If healthy_streak >= VERIFICATION_CHECKS:
     - Log: "Remediation verified: {service} healthy for {N} consecutive checks"
     - Clear healthy_streak

4. Check for INVESTIGATING incidents with no pending approvals:
   - These are incidents where all approvals were rejected
   - If metrics have returned to normal → auto-resolve
   - If metrics are still bad after 10 minutes → escalate (create new audit log entry)
```

**Post-remediation verification (GAP 5):**

When an incident transitions from "investigating" to "resolved" (via Executor completing approved action), the Watcher loop should verify the fix:

```python
async def verify_remediation(service: str, incident_id: str):
    """
    Called after Executor completes an action.
    Monitors the service for VERIFICATION_CHECKS consecutive healthy polls.
    If metrics stay bad, logs a warning and optionally creates a new incident.
    """
    healthy_count = 0
    for _ in range(VERIFICATION_CHECKS * 2):  # Give 2x checks worth of time
        await asyncio.sleep(POLL_INTERVAL)
        anomaly = await check_anomalies(service)
        if anomaly is None:
            healthy_count += 1
            if healthy_count >= VERIFICATION_CHECKS:
                # Remediation confirmed successful
                log_audit(f"Remediation verified for {service}: healthy for {healthy_count} checks")
                return True
        else:
            healthy_count = 0  # Reset on any anomaly
    
    # Remediation may not have worked
    log_audit(f"WARNING: {service} still anomalous after remediation for incident {incident_id}")
    return False
```

### 6.2 Modify `backend/main.py`

Start the watcher loop on backend startup:

```python
import asyncio
from agents.watcher_loop import watcher_loop

@app.on_event("startup")
async def startup_event():
    # ... existing startup code ...
    
    # Start always-on watcher with initial delay
    async def delayed_watcher():
        logger.info(f"Watcher will start in {INITIAL_DELAY}s (waiting for Prometheus)")
        await asyncio.sleep(INITIAL_DELAY)
        await watcher_loop()
    
    asyncio.create_task(delayed_watcher())
```

### 6.3 Wire Executor → Watcher Verification

In `backend/approval.py`, after the Executor completes an approved action:

```python
# After executor runs successfully:
if result["status"] == "completed":
    # Start verification in background
    asyncio.create_task(verify_remediation(service, incident_id))
```

---

## STEP 7: Backend API Changes

### 7.1 Modify `backend/dashboard_api.py`

**REMOVE**: `POST /api/run-scenario/{scenario}` endpoint and all related code.

**REMOVE**: All fixture/mock data reading logic. Remove imports of fixture files.

**MODIFY**: `GET /api/services/health` to use Prometheus:
```python
from backend.prometheus_client import get_all_services_health

@router.get("/api/services/health")
async def services_health():
    return await get_all_services_health()
```

**ADD**: Chaos injection endpoints:

```python
SERVICE_URLS = {
    "user-service": "http://user-service:8001",
    "payment-service": "http://payment-service:8002",
    "api-gateway": "http://api-gateway:8003",
}

@router.post("/api/chaos/inject")
async def inject_fault(body: dict):
    target = body["target"]          # "user-service"
    fault_type = body["type"]        # "memory_leak", "cpu_spike", "network_latency", "kill_service", "cache_failure"
    intensity = body.get("intensity", 90)
    duration = body.get("duration", 120)
    
    # Route to appropriate service chaos endpoint or Docker API
    if fault_type in ("memory_leak", "cpu_spike", "network_latency"):
        chaos_endpoint_map = {
            "memory_leak": f"/chaos/memory?percent={intensity}&duration={duration}",
            "cpu_spike": f"/chaos/cpu?cores={intensity}&duration={duration}",
            "network_latency": f"/chaos/latency?delay_ms={intensity}&duration={duration}",
        }
        url = SERVICE_URLS[target] + chaos_endpoint_map[fault_type]
        async with httpx.AsyncClient() as client:
            resp = await client.post(url)
            result = resp.json()
    elif fault_type == "kill_service":
        import docker
        d = docker.from_env()
        d.containers.get(f"sentinel-{target}").stop()
        result = {"status": "killed", "target": target}
    elif fault_type == "cache_failure":
        import docker
        d = docker.from_env()
        d.containers.get("sentinel-redis").stop()
        result = {"status": "redis_stopped"}
    else:
        return {"error": f"Unknown fault: {fault_type}"}
    
    # Log to audit
    db = SessionLocal()
    db.add(AuditLog(agent_name="chaos_injector", action=f"inject_{fault_type}",
                     tool_name="chaos_server", tool_input=json.dumps(body),
                     tool_output=json.dumps(result)))
    db.commit()
    db.close()
    
    return {"status": "injecting", "fault": fault_type, "target": target, "duration": duration}

@router.post("/api/chaos/stop")
async def stop_chaos(body: dict):
    target = body["target"]
    url = SERVICE_URLS[target] + "/chaos/stop"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url)
    return resp.json()

@router.get("/api/watcher/status")
async def watcher_status():
    from agents.watcher_loop import _last_check, _anomaly_streak, SERVICES, POLL_INTERVAL
    return {
        "enabled": True,
        "poll_interval_seconds": POLL_INTERVAL,
        "services_monitored": SERVICES,
        "last_check": _last_check,
        "anomaly_streaks": _anomaly_streak,
    }
```

### 7.2 Modify `backend/models.py`

Add to the `Incident` model:

```python
detection_metrics = Column(JSON, nullable=True)  # Prometheus values at detection time
detection_source = Column(String(50), default="live_metrics")  # "live_metrics" or "chaos_injection"
```

Create an Alembic migration for these new columns.

### 7.3 Remove `backend/seed_db.py` and `backend/mock_data_generator.py`

These are no longer needed. The database is populated by real incident detection from the Watcher loop. Remove all seed/fixture-related code.

Remove the `POST /api/dev/reset` endpoint or repurpose it to just clear the database without seeding fixtures.

---

## STEP 8: Frontend Changes

### 8.1 Delete `frontend/src/components/run-scenario-dialog.tsx`

This component is no longer needed.

### 8.2 Create `frontend/src/components/inject-fault-dialog.tsx`

New dialog component that replaces Run Scenario. It should:

- Be triggered by a button in the header (where "Run Scenario" was)
- Show a dropdown to select target service: user-service, payment-service, api-gateway
  - For "Cache Failure" type, target is automatically set to "redis" and the service dropdown is disabled
- Show radio buttons for exactly these 5 fault types with descriptions:
  - **Memory Leak**: "Gradually consume memory to 90%+. Triggers OOM errors, GC thrashing, connection pool exhaustion. Fix: restart + scale."
  - **CPU Spike**: "Max out CPU cores to 95%+. Triggers slow responses, request timeouts. Fix: scale + restart."
  - **Network Latency**: "Add 500ms delay to all network traffic. Triggers upstream timeouts, extreme response times. Fix: restart (resets network) + scale."
  - **Kill Service**: "Stop the container entirely. Triggers health check failure, dependent service errors. Fix: restart."
  - **Cache Failure**: "Stop Redis. All cache-dependent services degrade with connection errors. Fix: restart Redis + flush cache."
- Duration selector: 60s, 120s, 300s (not applicable for kill_service and cache_failure — those are instant)
- Warning text: "⚠️ This will actually break the target service. The AI agents will detect and respond automatically within 30-60 seconds."
- "Inject Fault" button calls `POST /api/chaos/inject`
- After injection, show a toast: "Fault injected on {service}. Watcher will detect the anomaly within 30-60 seconds."
- Do NOT show any scenario descriptions or mock data references

### 8.3 Modify `frontend/src/components/header.tsx`

Replace "Run Scenario" button with "Inject Fault" button that opens the new dialog.

### 8.4 Modify `frontend/src/app/page.tsx` (Dashboard)

**Service Health section**: Already polls `/api/services/health`. Increase polling frequency to every 5 seconds (from whatever it currently is). The data shape doesn't change — it's the same fields, just live from Prometheus now.

**Active Incidents section**: Change empty state text:
- FROM: "No active incidents. 3 resolved in database — View all or run a scenario to create new ones."
- TO: "All services healthy. Monitoring 3 services in real-time."

**Add Watcher status indicator**: Below the header or above Active Incidents, show a small status bar. Poll `GET /api/watcher/status` every 10 seconds:
```
🟢 Watcher active · Last check: 5s ago · Monitoring 3 services
```
When an anomaly streak is active:
```
🟡 Watcher active · Anomaly detected on user-service (streak: 2/2) · Monitoring 3 services
```

**Add Active Chaos banner**: When chaos is injected, show a prominent banner:
```
⚠️ Active fault: memory_leak on user-service · Injected 45s ago
```
This can be tracked via local state after the inject-fault-dialog returns success, with a countdown timer based on the duration.

**KPI cards**: No changes needed. They read from the same `/api/dashboard/stats` endpoint which queries Postgres. Incidents created by the live Watcher loop populate the same tables.

**Agent Status cards**: No changes needed. They read from `/api/agent-decisions`.

### 8.5 Modify `frontend/src/lib/api.ts`

Remove:
```typescript
export const runScenario = (scenario: string) => ...
```

Add:
```typescript
export const injectFault = (target: string, type: string, intensity: number, duration: number) =>
  post('/api/chaos/inject', { target, type, intensity, duration })

export const stopChaos = (target: string) =>
  post('/api/chaos/stop', { target })

export const getWatcherStatus = () =>
  get('/api/watcher/status')
```

### 8.6 Modify `frontend/src/contexts/run-scenario-context.tsx`

Rename to `inject-fault-context.tsx` or remove entirely if the inject-fault-dialog manages its own state. Remove all references to "scenario" in contexts.

### 8.7 Remove scenario references from sidebar

If the sidebar has any scenario-related text or hints, update them to reference fault injection instead.

---

## STEP 9: Docker Compose — Full Stack

### 9.1 Rewrite `docker-compose.yml`

The complete docker-compose.yml should include all 13 services. See the docker-compose.yml from the design document (Section 2 of the earlier artifact). Key points:

- All microservices use `cap_add: [NET_ADMIN]` for tc network chaos
- Backend mounts `/var/run/docker.sock` for Docker API access
- Backend has `PROMETHEUS_URL`, `LOKI_URL`, `WATCHER_ENABLED=1`, `WATCHER_POLL_INTERVAL=30`
- Grafana runs on port 3001 (to avoid conflict with Next.js on 3000)
- All services are on the `sentinel-net` Docker network
- Prometheus has 7-day retention and scrapes services every 10-15 seconds

### 9.2 Update `docker/Dockerfile.backend`

Ensure the backend Dockerfile includes:
```
RUN pip install docker httpx
```
So the backend can use the Docker Python SDK and httpx for Prometheus/Loki queries.

### 9.3 Create `frontend/Dockerfile` (if it doesn't exist)

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
```

---

## STEP 10: Cleanup — Remove All Mock/Fixture Code

### 10.1 Files to delete:
- `backend/seed_db.py` — no more seeding
- `backend/mock_data_generator.py` — no more mock generation
- `tests/fixtures/memory_leak.json` — no more fixtures
- `tests/fixtures/bad_deployment.json` — no more fixtures
- `tests/fixtures/api_timeout.json` — no more fixtures
- `tests/fixtures/_summary.json` — no more fixtures
- `frontend/src/components/run-scenario-dialog.tsx` — replaced by inject-fault-dialog

### 10.2 Code to remove from existing files:
- Any `load_fixture()`, `read_fixture()`, or JSON file reading in MCP servers
- Any `scenario` parameter in agent function signatures
- Any scenario-specific logic in agents (e.g., `if scenario == "memory_leak"`)
- The `POST /api/run-scenario/{scenario}` endpoint in dashboard_api.py
- The `POST /api/dev/reset` seed logic (keep the endpoint but just clear tables, no re-seed)
- Fixture imports in any file
- The `SCENARIO_REGISTRY` in mock_data_generator.py
- All references to `rollback_deployment` in agents/strategist.py, agents/executor_crew.py, mcp_servers/infra_server.py
- All references to `update_config` in agents/strategist.py, mcp_servers/infra_server.py
- All references to `bad_deployment` as a scenario or fault type
- All references to `packet_loss` as a fault type
- The DANGEROUS risk level — we only have SAFE and RISKY now (no rollback = no dangerous actions)

### 10.3 Environment variables to update:
In `.env` / `.env.example`:
```
# ADD:
PROMETHEUS_URL=http://prometheus:9090
LOKI_URL=http://loki:3100
WATCHER_ENABLED=1
WATCHER_POLL_INTERVAL=30

# KEEP:
GROQ_API_KEY=...
DATABASE_URL=postgresql://sentinel:sentinel@postgres:5432/sentinelai

# REMOVE:
SENTINEL_DEV_MODE=1  (no longer needed, no mock mode)
```

---

## STEP 11: Testing the Full Flow

After all changes are implemented, test each of the 5 scenarios:

```bash
# 1. Start everything
docker-compose up --build -d

# 2. Wait 60 seconds for Prometheus to collect initial metrics
#    and for the Watcher loop to start

# 3. Open dashboard at http://localhost:3000
#    - Should show 0 active incidents
#    - Service Health should show live metrics (CPU ~10-30%, Memory ~20-40%)
#    - Watcher status should show "active"
```

### Test Scenario 1: Memory Leak
```
4. Click "Inject Fault" → Memory Leak → user-service → 120s → Inject
5. Watch dashboard:
   - Service Health: user-service memory climbs to 85%+
   - After ~60s: Watcher triggers pipeline
   - Active Incidents: new incident appears
   - Approvals: pending restart action (RISKY) + auto-executed scale (SAFE)
6. Go to Approvals → Approve restart
7. Watch: memory drops to ~20%, incident resolves
8. Watcher verifies: 3 healthy checks → "Remediation verified"
```

### Test Scenario 2: CPU Spike
```
9. Click "Inject Fault" → CPU Spike → payment-service → 60s → Inject
10. Watcher detects CPU > 80%, triggers pipeline
11. Diagnostician finds: high CPU, normal memory → pattern: cpu_exhaustion
12. Strategist: scale (SAFE, auto) + restart (RISKY, needs approval)
13. Approve restart → CPU normalizes → verified
```

### Test Scenario 3: Network Latency
```
14. Click "Inject Fault" → Network Latency → api-gateway → 120s → Inject
15. Watcher detects extreme response times with normal CPU/memory
16. Diagnostician finds: upstream timeouts, normal resources → pattern: network_issue
17. Strategist: scale (SAFE) + restart (RISKY) — restart resets tc rules
18. Approve restart → latency normalizes → verified
```

### Test Scenario 4: Kill Service
```
19. Click "Inject Fault" → Kill Service → user-service → Inject
20. Watcher detects up=0, no metrics → pattern: service_down
21. Diagnostician confirms container exited
22. Strategist: restart (RISKY)
23. Approve restart → service comes back → verified
```

### Test Scenario 5: Cache Failure
```
24. Click "Inject Fault" → Cache Failure → Inject (targets Redis)
25. Watcher detects MULTIPLE services degraded simultaneously
26. Diagnostician finds Redis down + cache errors across all services → pattern: cache_failure
27. Strategist: restart redis (RISKY) + flush_cache (SAFE)
28. Approve restart → Redis comes back → all services recover → verified
```

```bash
# Optional: Check Grafana at http://localhost:3001 (admin/sentinel)
# See the metric spikes and recovery in real Prometheus graphs
```

---

## SUMMARY: All Files Changed

```
NEW FILES (~16):
  services/user-service/app.py
  services/user-service/Dockerfile
  services/user-service/requirements.txt
  services/payment-service/app.py
  services/payment-service/Dockerfile
  services/payment-service/requirements.txt
  services/api-gateway/app.py
  services/api-gateway/Dockerfile
  services/api-gateway/requirements.txt
  monitoring/prometheus/prometheus.yml
  monitoring/prometheus/alert_rules.yml
  monitoring/loki/loki-config.yml
  monitoring/promtail/promtail-config.yml
  monitoring/grafana/provisioning/datasources/datasources.yml
  backend/prometheus_client.py
  agents/watcher_loop.py
  frontend/src/components/inject-fault-dialog.tsx

MODIFIED FILES (~11):
  mcp_servers/metrics_server.py (remove fixtures, add Prometheus queries)
  mcp_servers/logs_server.py (remove fixtures, add Loki queries)
  mcp_servers/infra_server.py (remove mocks, add Docker API — only restart, scale, flush_cache)
  agents/watcher.py (remove scenario param, new metric-aware prompt)
  agents/diagnostician.py (remove scenario param, new autonomous diagnosis prompt with decision tree)
  agents/strategist.py (remove scenario param, only SAFE/RISKY actions, no rollback/config)
  agents/executor_crew.py (real Docker tools — restart, scale, flush_cache only)
  backend/main.py (start watcher loop on startup with 60s delay)
  backend/dashboard_api.py (remove run-scenario, add 5 chaos inject types, add watcher status)
  backend/models.py (add detection_metrics JSONB, detection_source)
  frontend/src/app/page.tsx (live metrics, watcher status, chaos banner)
  frontend/src/components/header.tsx (Inject Fault button replaces Run Scenario)
  frontend/src/lib/api.ts (injectFault, stopChaos, getWatcherStatus — remove runScenario)
  docker-compose.yml (full rewrite with 13 services)

DELETED FILES (~8):
  backend/seed_db.py
  backend/mock_data_generator.py
  tests/fixtures/memory_leak.json
  tests/fixtures/bad_deployment.json
  tests/fixtures/api_timeout.json
  tests/fixtures/_summary.json
  frontend/src/components/run-scenario-dialog.tsx
  frontend/src/contexts/run-scenario-context.tsx (if it exists)
```

---

## VALIDATION CHECKLIST

Before considering this complete, verify:

```
□ All 3 microservices start and expose /metrics and /health
□ Prometheus scrapes all 3 services (check http://localhost:9090/targets)
□ Loki receives logs from all containers (check Grafana → Explore → Loki)
□ Watcher loop starts 60s after backend boot (check backend logs)
□ Watcher correctly ignores normal metrics (no false positives)
□ Memory leak injection → Watcher detects after 2 polls → pipeline triggers
□ Diagnostician correctly identifies memory_leak pattern (NOT cpu_exhaustion)
□ CPU spike injection → Diagnostician identifies cpu_exhaustion (NOT memory_leak)
□ Network latency → Diagnostician identifies network_issue (normal CPU/memory is the key signal)
□ Kill service → Watcher handles missing metrics gracefully → identifies service_down
□ Cache failure → Watcher detects multi-service degradation → Diagnostician finds Redis down
□ Strategist only suggests restart_service, scale_service, flush_cache (no rollback/config)
□ Executor actually restarts containers via Docker API
□ Executor actually scales via docker-compose scale
□ Post-restart, Watcher verifies metrics normalized → incident resolves
□ Approvals page shows RISKY actions correctly
□ SAFE actions auto-execute without approval
□ No references to fixtures, scenarios, rollback_deployment, or update_config remain in codebase
□ Frontend shows "Inject Fault" not "Run Scenario"
□ Dashboard Service Health bars update in real-time from Prometheus
```