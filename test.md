## SentinelAI Live Stack — End‑to‑End Test Guide

This guide walks you through validating the **live, non‑mock** SentinelAI stack using Docker Compose, chaos injection, and the dashboard. It focuses on:

- Verifying the stack boots correctly.
- Validating metrics/logs wiring (Prometheus + Loki).
- Exercising each fault type and watching the agents respond.
- Knowing what "healthy" vs "broken" vs "recovered" looks like.

---

## 1. Prerequisites

- **Docker + Docker Compose** installed and running.
- **Ports** available on your host:
  - Backend: `8000`
  - Frontend: `3000`
  - Prometheus: `9090`
  - Grafana: `3001`
  - Loki: `3100`
  - cAdvisor: `8080`
- `.env` created from `.env.example` with a valid `GROQ_API_KEY`.

Quick check:

```bash
cd /Users/akshay/Desktop/Sentinel-AI
cp .env.example .env          # if you haven’t already
# Edit .env and set GROQ_API_KEY
```

---

## 2. Starting the Full Stack

From the repo root:

```bash
docker-compose up --build -d
```

What this does:

- Starts:
  - `postgres`, `redis`
  - `user-service`, `payment-service`, `api-gateway`
  - `backend` (FastAPI, watcher loop)
  - `frontend` (Next.js dashboard)
  - `prometheus`, `cadvisor`, `loki`, `promtail`, `grafana`
- Wires everything onto the `sentinel-net` network.

### 2.1. Initial health check (first 60–90 seconds)

Right after `docker-compose up`:

1. Run:
   ```bash
   docker ps
   ```
   You should see containers:
   - `sentinel-backend`, `sentinel-frontend`
   - `sentinel-user-service`, `sentinel-payment-service`, `sentinel-api-gateway`
   - `sentinel-postgres`, `sentinel-redis`
   - `sentinel-prometheus`, `sentinel-loki`, `sentinel-promtail`, `sentinel-cadvisor`, `sentinel-grafana`

2. Wait ~60 seconds for:
   - Services to start their own `/metrics` endpoints.
   - Prometheus to perform at least one scrape.
   - Watcher loop initial warm‑up delay to elapse.

---

## 3. Baseline: System Healthy, No Faults

### 3.1. Frontend dashboard

Open:

- Dashboard: `http://localhost:3000`

Check:

- **Watcher bar** at the top:
  - Text like:  
    `Watcher active · polling every 30s · monitoring 3 services`
  - If you leave it open for a bit, `Last check` time should update periodically.
- **Service Health** card:
  - Lists `user-service`, `payment-service`, `api-gateway`.
  - Each should have:
    - `status` = `healthy` (or possibly `unknown` for the first minute).
    - CPU/Memory progress bars not pegged at 100%.
    - Error rate close to 0%.
- **Active Incidents** section:
  - Ideally:  
    `All services healthy. Monitoring 3 services in real-time.`
  - If you have historic data, you may see resolved incidents in the DB, but **no open incidents**.

If the dashboard shows an API error:

- Confirm backend:
  ```bash
  curl http://localhost:8000/health
  ```
  Should return `{"status": "healthy", "service": "sentinelai"}`.
- Confirm frontend `NEXT_PUBLIC_API_URL` in `.env` is `http://localhost:8000`.

### 3.2. Prometheus / Grafana quick peek (optional but recommended)

- Prometheus UI: `http://localhost:9090`
  - Try a query:
    - `service_cpu_percent`
    - You should see time series for `user-service`, `payment-service`, `api-gateway`.
- Grafana: `http://localhost:3001` (user: `admin`, password: `sentinel`)
  - Verify data sources:
    - Prometheus (`http://prometheus:9090`)
    - Loki (`http://loki:3100`)

---

## 4. Testing Each Fault Scenario

All fault injections use the frontend **Inject Fault** dialog (top‑right button in the header).

General expectations for **every** fault:

1. You inject a fault.
2. Within ~30–90 seconds:
   - Prometheus metrics reflect the issue (CPU/memory/error‑rate/latency).
   - Watcher detects an anomaly for the affected service (or multi‑service in cache failure).
   - Dashboard shows a new **Open incident**.
3. Diagnostician and Strategist run:
   - You see new entries in:
     - `/api/agent-decisions`
     - `/api/audit-logs`
4. When you approve risky actions (via the Approvals page), Executor runs:
   - The service recovers.
   - Watcher anomaly streaks reset.
   - Incident status becomes `resolved`.

### 4.1. Scenario 1 — Memory Leak on `user-service`

In the dashboard:

1. Click **Inject Fault**.
2. Set:
   - Target Service: `user-service`
   - Fault Type: `Memory Leak`
   - Duration: `120s`
3. Click **Inject Fault**.

What should happen:

- **Immediately**:
  - Banner: `Active fault: memory_leak on user-service`.
  - In `docker ps`, `sentinel-user-service` remains running.
- **Within ~30–60s**:
  - Prometheus:
    - `service_memory_percent{service="user-service"}` climbs above ~85%.
    - `service_db_connections_active` and `service_gc_pause_ms` increase.
  - Dashboard:
    - `user-service` status goes to `warning` → `critical` (depending on thresholds).
    - Active incidents: new incident like `[Watcher] ... user-service ... memory leak ...`.
  - Watcher status bar:
    - Shows an anomaly streak for `user-service` ≥ 1.
- **Diagnostician & Strategist**:
  - Incident trace (`/api/agent-trace/{incident_id}`) should show:
    - Watcher decision with elevated memory metrics.
    - Diagnostician root cause category close to `"memory_leak"` (LLM wording may vary).
    - Strategist plan: scale + restart user-service.
- **After you approve** any pending restart/scale actions:
  - `user-service` is restarted (and possibly scaled).
  - Memory usage returns to normal.
  - A few watcher polls later, `user-service` status returns to `healthy`.
  - Incident status changes to `resolved`.

### 4.2. Scenario 2 — CPU Spike on `payment-service`

Steps:

1. Inject fault:
   - Target: `payment-service`
   - Fault: `CPU Spike`
   - Duration: `60s`

Expected signals:

- `service_cpu_percent{service="payment-service"}` close to 100%.
- Gateway and/or payment responses might slow or produce 5xx/504s.
- Watcher triggers an incident on `payment-service`:
  - Increased CPU.
  - Possibly higher `http_request_duration_seconds` and error rate.
- Diagnostician:
  - Root cause category along lines of `"cpu_exhaustion"` / `"api_timeout"` depending on pattern.
- Strategist:
  - Plan includes scaling up and restarting `payment-service`.
- After approvals:
  - CPU metric returns to normal.
  - Service status back to `healthy`.

### 4.3. Scenario 3 — Network Latency on `api-gateway`

Steps:

1. Inject fault:
   - Target: `api-gateway`
   - Fault: `Network Latency`
   - Duration: `120s`

Expected:

- `gateway_upstream_latency_seconds{service="api-gateway"}` increases.
- `http_request_duration_seconds{service="api-gateway"}` p95 grows.
- Error rate (504s) may increase.
- Watcher:
  - Detects anomaly for `api-gateway` (high latency/error rate).
  - New incident focused on gateway/network issues.
- Diagnostician:
  - Root cause category like `"api_timeout"` / `"network_issue"`.
- Strategist:
  - Plan suggests restart + possible scale up on `api-gateway`.

### 4.4. Scenario 4 — Kill `user-service` Container

Steps:

1. Inject fault:
   - Target: `user-service`
   - Fault: `Kill Service`
2. This stops the `sentinel-user-service` container (Docker stop).

Expected:

- Prometheus `up{job="user-service"}` becomes `0`.
- `check_anomalies("user-service")` treats this as `service_down`:
  - Anomaly on metric `up` with `severity="critical"`.
  - `detection_metrics.status="down"`.
- Dashboard:
  - `user-service` status → `critical`.
  - New incident clearly indicating service unavailability.
- Diagnostician:
  - Root cause category similar to `"service_down"` / `"infrastructure"`.
- Strategist:
  - Plan uses `restart_service` on `user-service`.
- After approval:
  - InfraMCP starts the container (because it detects `status="exited"` and uses `.start()`).
  - Watcher sees `up` back to 1 and service returns to `healthy`.

### 4.5. Scenario 5 — Cache Failure (Redis Down, Multi‑Service)

Steps:

1. Inject fault:
   - Fault Type: `Cache Failure` (target will auto‑set to `redis`).

Expected:

- Docker:
  - `sentinel-redis` container stops.
- Services:
  - `payment-service` and `api-gateway` logs show Redis connection errors.
  - Error rates and/or latencies increase for multiple services.
- Watcher loop multi‑service logic:
  - Sees anomaly streaks on **two or more** services.
  - Detects that `sentinel-redis` is not running.
  - Triggers a **single** pipeline for a synthetic `redis` incident, with:
    - `detection_metrics.status="down"`.
    - `affected_services` list including `user-service`/`payment-service`/`api-gateway`.
  - It should **not** create separate, redundant incidents for each downstream service if the Redis incident is already open.
- After you approve any Redis restart action:
  - InfraMCP restarts `sentinel-redis` and automatically calls `flush_cache` as a post‑step.
  - Services recover, error rates drop, and the Redis incident is resolved.

### 4.6. Scenario 6 — Concurrent Faults (Memory on user + CPU on payment)

Steps:

1. Inject `Memory Leak` on `user-service`.
2. Shortly after (before the first incident fully resolves), inject `CPU Spike` on `payment-service`.

Expected:

- Two distinct incidents:
  - One associated with `user-service` memory issues.
  - Another with `payment-service` CPU/timeouts.
- Watcher loop:
  - Tracks independent anomaly streaks per service.
  - Runs the pipeline separately for each, **unless** a shared dependency like Redis is down (see cache failure case).
- Approvals:
  - You should see separate approval entries (if risky actions are requested) for each service.
  - Resolving one should not automatically resolve the other; both need remediation.

---

## 5. Where to Inspect Internals

To go deeper than the UI:

- **Incidents**:
  - `GET /api/incidents?status=open`
  - `GET /api/agent-trace/{incident_id}`
  - `GET /api/incidents/{incident_id}/events`
- **Agent decisions**:
  - `GET /api/agent-decisions`
- **Audit logs (tool calls)**:
  - `GET /api/audit-logs?incident_id={incident_id}`
- **Watcher status**:
  - `GET /api/watcher/status`

You can hit these either via the frontend (the dashboard uses them) or directly with `curl`/`httpie`.

---

## 6. Interpreting “Odd” Results

If something looks wrong, use this as a quick diagnostic checklist:

- **No metrics / all statuses unknown**:
  - Confirm Prometheus is up (`http://localhost:9090`).
  - Check that microservices expose `/metrics` and Prometheus `prometheus.yml` is scraping them.
- **No incidents despite obvious faults**:
  - Ensure watcher loop is enabled:
    - `WATCHER_ENABLED=1` in `.env`.
    - `/api/watcher/status` shows `enabled: true` and a recent `last_check`.
- **Incidents created but never resolved**:
  - Check Approvals page for pending risky actions.
  - After you approve them, confirm:
    - Executor audit logs show `restart_service` / `scale_service` executions.
    - `verify_remediation` logs (backend) indicate successful health checks and scale‑down to 1 replica if applicable.
- **Multi‑service cascading noise**:
  - If you see many incidents for downstream services during a `cache_failure`, verify:
    - There is exactly **one** open incident for `redis`.
    - Additional downstream incidents are being skipped when a Redis incident is open (cascading deduplication).

If any scenario consistently deviates from the “Expected” sections above (wrong root cause category, no incidents, incidents never resolving), capture:

- Which fault type and target you used.
- Approximate timestamps.
- Relevant snippets from:
  - `/api/watcher/status`
  - `/api/incidents` and `/api/agent-trace/{id}`
  - Backend logs for the timeframe.

…and we can then adjust the corresponding watcher/diagnostician/strategist or microservice behavior based on that evidence.

