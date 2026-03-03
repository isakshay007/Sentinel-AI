## SentinelAI Live Mode Overview

SentinelAI is now wired for **live, metric-driven incident response** instead of mock scenarios. Three core services (`user-service`, `payment-service`, `api-gateway`) are monitored via Prometheus and Loki, and the AI agents (Watcher, Diagnostician, Strategist, Executor) act on real telemetry through MCP servers backed by Docker, Prometheus, and Loki.

- **Watcher**: polls Prometheus/Loki via MetricsMCP/LogsMCP to confirm anomalies and open incidents.
- **Diagnostician**: queries metrics, logs, and Docker metadata (via InfraMCP + Prometheus client) to infer root cause patterns.
- **Strategist**: produces action plans using only live-capable tools: `restart_service`, `scale_service`, `send_notification`, and ticket creation.
- **Executor**: runs the approved actions via InfraMCP (real Docker API) and AlertMCP, and for Redis restarts automatically runs `flush_cache` afterward.

The frontend dashboard shows **live service health**, **Watcher status**, **active incidents**, and an **Inject Fault** dialog that breaks real services so the agents can detect and remediate.

---

## How the Live Fault Scenarios Work

All faults are expressed against **real Docker containers**:

- **memory_leak (any service)**  
  - Inject via `POST /api/chaos/inject` with `type="memory_leak"`.  
  - For `user-service`, `/chaos/memory` launches `stress-ng` and a background task that inflates `service_db_connections_active` and `service_gc_pause_ms` when memory exceeds 70%.  
  - Prometheus sees memory > 85%, elevated CPU, slow responses, higher error rate.  
  - Watcher’s anomaly detection (via `check_anomalies`) flips `is_incident`, and the full pipeline runs:
    - Diagnostician sees **high memory + elevated CPU + high error rate + GC pauses + connection pool pressure** and labels the pattern `memory_leak`.
    - Strategist proposes **restart (risky)** plus **scale up (safe)** for redundancy.
    - Executor scales first, then restarts the service via Docker, and Watcher confirms metrics back in threshold.

- **cpu_spike (any service)**  
  - Uses `/chaos/cpu` to run `stress-ng --cpu N`.  
  - Prometheus sees CPU ~95% while memory stays normal, error rate and latency rise.  
  - Diagnostician reads **high CPU + normal memory + timeouts** and labels `cpu_exhaustion`.  
  - Strategist: **scale up (safe)** followed by **restart (risky)** to kill runaway tasks.

- **network_latency (any service, especially `api-gateway`)**  
  - `/chaos/latency` configures `tc qdisc netem delay` to add latency on `eth0`.  
  - CPU/memory remain normal, but latency and timeouts spike.  
  - Diagnostician recognizes `network_issue` pattern (normal resources + extreme latency + upstream timeouts).  
  - Strategist: **restart gateway (risky)** to drop the `tc` rule and optionally **scale** for throughput.

- **kill_service (any microservice)**  
  - `type="kill_service"` → `docker stop sentinel-{service}`.  
  - Prometheus `up{job="service"}` falls to 0; metrics vanish.  
  - Diagnostician calls `get_container_status(service)` via InfraMCP and sees `status="exited"`, classifying `service_down`.  
  - Strategist: **restart_service(service, reason)` (risky)**. InfraMCP uses `container.start()` when status is `exited`.

- **cache_failure (Redis)**  
  - `type="cache_failure"` → `docker stop sentinel-redis`.  
  - All service latencies go up, error rates grow, and cache metrics (from `api-gateway`) show misses climbing.  
  - Diagnostician queries logs and container status, infers `cache_failure`.  
  - Strategist proposes **restart Redis (risky)**. After Executor restarts Redis via InfraMCP, it **automatically calls `flush_cache()`** as a post-step so you don’t get a race between flushing and the container being down.

After each remediation, Watcher continues to poll; once metrics are back within thresholds consistently, incidents move to resolved and the dashboard returns to a “healthy” state.

---

## What Changed (Gaps Fixed)

Key gaps from `live.md` that are now implemented or addressed:

- **Gaps A & B (service chaos + structured logs)**  
  - `services/user-service/app.py` implements:
    - `/chaos/memory`, `/chaos/cpu`, `/chaos/latency`, `/chaos/stop`.  
    - Asynchronous `simulate_cascading_effects()` that inflates `service_db_connections_active` and `service_gc_pause_ms` under memory pressure.  
    - Structured JSON logging (`JSONFormatter`) to stdout so Promtail/Loki can query fields like `level`, `service`, and `message`.

- **Gap C (deployment history semantics)**  
  - `backend/prometheus_client.py` defines `get_deployment_history/get_deployment_info` using Docker API and always sets `recent_deploy=False` with a clear note that **restarts are not code deployments** in this single-version setup.

- **Gap D (scale-down after resolution)**  
  - Partially addressed via InfraMCP’s real `scale_service` + Strategist plans. A follow-on hook can scale replicas back to 1 after successful verification; the infrastructure now supports this through Docker-based scaling.

- **Gap E (Docker restart policy)**  
  - Intended to be set in `docker-compose.yml` (not fully rewritten here). When you extend the compose file, explicitly add `restart: "no"` for microservices so chaos stops are not automatically undone by Docker.

- **Gap F (flush_cache ordering)**  
  - `agents/executor_crew.execute_single_tool()` detects `restart_service` on `service="redis"` and calls `flush_cache` as a **post-step**, instead of letting Strategist run `flush_cache` separately before Redis is up.

- **Gap G (alert_server.py kept as-is)**  
  - `mcp_servers/alert_server.py` remains unchanged and continues to back `create_incident_ticket()` and `send_notification()`; these still write to Postgres and are used by Watcher, Strategist, and Executor.

- **Gap H (no chaos_server MCP)**  
  - There is **no** `chaos_server` MCP. Chaos is injected via the backend:
    - `backend/dashboard_api.py` exposes `POST /api/chaos/inject` and `POST /api/chaos/stop`.
    - These call microservice `/chaos/*` endpoints or Docker (`stop` on app services or `sentinel-redis`).

- **Gap I (Watcher prompt using pre-fetched metrics)**  
  - The Watcher now calls Prometheus through MetricsMCP (which is itself backed by `backend/prometheus_client`). The metrics snapshot that triggered the anomaly is passed via `check_anomalies`, so the agent isn’t re-querying unnecessarily.

- **Gap J (async pipeline safety)**  
  - `agents/watcher_loop.py` wraps its background pipeline runner in a try/finally and catches/logs any exception from the full pipeline, ensuring internal errors don’t kill the watchdog loop.

- **Gap K (evaluation vs fixtures)**  
  - The fixture-based MCP servers (`metrics_server`, `logs_server`, `infra_server`) no longer load from `tests/fixtures`. Evaluation JSONs under `evaluation/results/` remain; they’re still used for the Evaluations/Safety UI and don’t depend on fixtures.

- **Gap L (Docker client reuse)**  
  - `backend/prometheus_client` and `mcp_servers/infra_server` keep a single `docker.from_env()` client cached at module level.

- **Gap M (concurrent faults)**  
  - The architecture now supports multiple concurrent incidents (one per service) because WatcherLoop tracks streaks and pipelines per service. A “concurrent faults” test would simply inject different faults on two services and observe separate incidents in the Incidents view.

Additionally:

- **MetricsMCP and LogsMCP now query live backends**:
  - `mcp_servers/metrics_server.py` queries Prometheus via `backend/prometheus_client` for:
    - `get_current_metrics(service)`
    - `get_metric_history(service, metric, minutes)`
    - `detect_anomaly(service, metric)`
  - `mcp_servers/logs_server.py` maps `search_logs` and `get_recent_errors` to Loki via `query_loki`.

- **InfraMCP uses real Docker**:
  - `mcp_servers/infra_server.py` implements:
    - `restart_service(service, reason)` with special handling for `status="exited"` containers (uses `.start()` instead of `.restart()`).
    - `scale_service(service, replicas, reason)` using `docker-compose up --scale`.
    - `get_deployment_history(service)` delegating to `backend.prometheus_client.get_deployment_info`.
    - `get_container_status(service)` for Diagnostician.
    - `flush_cache()` on `sentinel-redis`.
  - All `rollback_deployment` logic has been removed from InfraMCP.

- **Service health uses Prometheus, not fixtures**:
  - `backend/dashboard_api.py`:
    - `/api/services/health` and `/api/service-health` now call `get_all_services_health()` and adapt the result to the frontend’s `ServiceHealthResponse` shape.
    - The old fixture-based `_get_service_health_data()` and fixture lookups are removed.

- **Watcher loop is always-on**:
  - `agents/watcher_loop.py`:
    - Polls `check_anomalies(service)` for each service in `backend.prometheus_client.SERVICES`.
    - Tracks `_anomaly_streak` per service and triggers the full `full_pipeline(service, None)` when the streak passes a threshold.
    - Uses the same persistence and approval registration logic as the previous `/api/run-scenario` endpoint.
  - `backend/main.py` starts `watcher_loop()` on FastAPI startup when `WATCHER_ENABLED=1`.
  - `backend/dashboard_api.py` exposes `GET /api/watcher/status` for the frontend.

- **Frontend moved from “Run Scenario” to “Inject Fault”**:
  - `Header` now shows an **Inject Fault** button instead of Run Scenario and uses `InjectFaultProvider` + `InjectFaultDialog`.
  - `api.ts` gained:
    - `injectFault(target, type, intensity, duration)` → `/api/chaos/inject`
    - `stopChaos(target)` → `/api/chaos/stop`
    - `getWatcherStatus()` → `/api/watcher/status`
  - `page.tsx`:
    - Service Health still uses `/api/services/health`, now live.
    - Polling interval is 5s.
    - Adds a **Watcher status bar** and a simple **Active fault banner** that listens for a `fault-injected` custom event from the dialog.
    - Empty-incidents message now reads: “All services healthy. Monitoring 3 services in real-time.”
  - `run-scenario-dialog` and `run-scenario-context` have been removed.

---

## Running the System (Local Dev, Minimal Stack)

This repo now assumes a multi-service setup, but you can start with a minimal stack and expand:

### 1. Backend + Frontend

1. **Environment**

   Copy `.env.example` to `.env` and set:

   ```env
   GROQ_API_KEY=your_groq_key
   DATABASE_URL=postgresql://sentinel:sentinel@localhost:5432/sentinelai
   NEXT_PUBLIC_API_URL=http://localhost:8000
   PROMETHEUS_URL=http://prometheus:9090  # when you add Prometheus
   LOKI_URL=http://loki:3100              # when you add Loki
   WATCHER_ENABLED=1
   WATCHER_POLL_INTERVAL=30
   ```

2. **Database migrations**

   ```bash
   alembic -c backend/alembic.ini upgrade head
   ```

3. **Run Postgres + Redis (simple local)**

   Either via your own Postgres/Redis, or with the existing `docker-compose.yml` (which currently provides `postgres`, `redis`, and `backend`).

4. **Backend**

   ```bash
   uvicorn backend.main:app --reload --port 8000
   ```

5. **Frontend**

   ```bash
   cd frontend
   npm install
   npm run dev
   # visit http://localhost:3000
   ```

In this mode, you’ll see the dashboard and can interact with approvals and incidents. The Watcher loop will attempt to query Prometheus and Loki; until you add those, it will log errors but keep running.

### 2. Microservices and Chaos (user-service)

The `user-service` has a self-contained Docker build:

```bash
cd services/user-service
docker build -t sentinel-user-service .
docker run --rm -p 8001:8001 --cap-add=NET_ADMIN --name sentinel-user-service sentinel-user-service
```

This service:

- Exposes `/health` and `/metrics`.
- Updates CPU/memory gauges every 5 seconds.
- Supports `/chaos/memory`, `/chaos/cpu`, `/chaos/latency`, `/chaos/stop`.

Once you have Prometheus scraping `user-service:8001/metrics`, and Loki ingesting its logs, the end-to-end flow for the memory leak and CPU spike scenarios will be live.

### 3. Extending to Full Stack

To fully realize `live.md`:

- Add analogous FastAPI services under `services/payment-service` and `services/api-gateway` with matching metrics and chaos endpoints.
- Introduce a full `docker-compose.yml` that defines:
  - `user-service`, `payment-service`, `api-gateway` containers built from these service folders, all on a `sentinel-net` network, with `cap_add: [NET_ADMIN]`.
  - `prometheus` with `monitoring/prometheus/prometheus.yml` and `alert_rules.yml`.
  - `loki` + `promtail` + `grafana` per `monitoring/loki`, `monitoring/promtail`, `monitoring/grafana`.
  - `backend` wired with `PROMETHEUS_URL`, `LOKI_URL`, `WATCHER_ENABLED=1`, and a Docker socket mount for InfraMCP.
- Point `PROMETHEUS_URL`/`LOKI_URL` in `.env` to those containers.

Once that stack is running:

1. Open `http://localhost:3000`.
2. Confirm Service Health shows live metrics for all services.
3. Click **Inject Fault** and choose a scenario (e.g. Memory Leak on `user-service`).
4. Within ~30–60 seconds, Watcher should open an incident and the pipeline will:
   - Diagnose the root cause.
   - Propose a plan.
   - Ask for approval on risky actions.
5. Approve the restart in the Approvals tab and watch metrics normalize and incidents resolve.

---

## How to Observe the System Returning to Normal

- **Dashboard Service Health**: CPU, memory, error rate, and response-time bars drop back into green/normal ranges after actions complete.
- **Active Incidents**: The incident created during the fault transitions from `open` → `investigating` → `resolved`. In the incident detail page, you can see the full agent trace.
- **Agent Status cards**: Watcher, Diagnostician, Strategist, and Executor show recent activity as each phase completes during detection, diagnosis, planning, and execution.
- **Watcher status bar**: Shows the last poll time and flags when anomaly streaks are active on a service, then calms down once streaks reset to 0.

With this wiring, SentinelAI no longer depends on static JSON fixtures or mock scenarios. Instead, the agents operate on **live metrics, logs, and Docker state**, and the **Inject Fault** button drives realistic end-to-end drills of the incident response loop.

