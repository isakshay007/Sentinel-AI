# SentinelAI — MCP Tools Reference

## Overview

SentinelAI uses 4 MCP servers exposing 13 tools that agents can discover
and call at runtime via the Model Context Protocol.

```
┌─────────────────────────────────────────────────────────┐
│                    Agent (MCP Client)                    │
│         Discovers tools → Decides → Calls them          │
└────┬──────────┬──────────────┬──────────────┬───────────┘
     │          │              │              │
     ▼          ▼              ▼              ▼
┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ LogsMCP │ │MetricsMCP│ │ InfraMCP │ │ AlertMCP │
│ 3 tools │ │ 3 tools  │ │ 4 tools  │ │ 3 tools  │
└─────────┘ └──────────┘ └──────────┘ └──────────┘
```

---

## LogsMCP Server (mcp_servers/logs_server.py)

| Tool | Risk | Description |
|------|------|-------------|
| `search_logs` | safe | Search logs by keyword, severity, service, time range |
| `get_recent_errors` | safe | Get recent ERROR/WARN entries with service breakdown |

### search_logs
```
Args:
  query: str          — Search term (case-insensitive)
  severity: str?      — INFO, WARN, or ERROR
  service: str        — Service name (required in live mode)
  minutes_ago: int    — Time window (default: 60)
  max_results: int    — Max entries (default: 20)

Returns: { results: [...], total_matches: int, filters: {...} }
```

### get_recent_errors
```
Args:
  minutes: int          — Time window (default: 30)
  service: str          — Service name (required in live mode)
  include_warnings: bool — Include WARN level (default: true)
  max_results: int      — Max entries (default: 50)

Returns: { results: [...], summary: { total_entries, by_service } }
```

---

## MetricsMCP Server (mcp_servers/metrics_server.py)

| Tool | Risk | Description |
|------|------|-------------|
| `get_current_metrics` | safe | Latest CPU, memory, latency, error rate for a service |
| `get_metric_history` | safe | Time-series data with statistics and trend detection |
| `detect_anomaly` | safe | Threshold or statistical anomaly detection |

### get_current_metrics
```
Args:
  service: str — Service name

Returns: { metrics: { cpu_percent, memory_percent, response_time_ms, 
           error_rate, ... }, health_status, warnings }
```

### get_metric_history
```
Args:
  service: str    — Service name
  metric: str     — cpu_percent | memory_percent | response_time_ms | 
                     error_rate | gc_pause_ms | request_count
  minutes: int    — Time window (default: 60)

Returns: { series: [{timestamp, value}...], statistics: { min, max, 
           mean, median, stdev, trend, change_percent } }
```

### detect_anomaly
```
Args:
  service: str    — Service name
  metric: str     — Metric to check

Returns: { is_anomalous: bool, severity: "normal"|"warning"|"critical",
           evidence: { current_value, threshold } }
```

---

## InfraMCP Server (mcp_servers/infra_server.py)

| Tool | Risk | Description |
|------|------|-------------|
| `restart_service` | **risky** | Restart or start a container |
| `scale_service` | safe/risky | Scale replicas up (safe) or down (risky) |
| `get_deployment_history` | safe | Container image and restart info |

### restart_service
```
⚠️ RISK: RISKY — Temporary downtime during restart

Args:
  service: str  — Service to restart
  reason: str   — Audit reason

Returns: { total_downtime_seconds, phases: { drain, stop, start },
           service_state, audit_id }
```

### scale_service
```
Args:
  service: str   — Service to scale
  replicas: int  — Target count (1-10)
  reason: str    — Audit reason

Returns: { previous_replicas, new_replicas, direction, 
           scale_time_seconds, audit_id }
```

### get_deployment_history
```
Args:
  service: str  — Service name

Returns: { deployment_info: { current_image, status, started_at, restart_count, recent_deploy, note } }
```

---

## AlertMCP Server (mcp_servers/alert_server.py)

| Tool | Risk | Description |
|------|------|-------------|
| `send_notification` | safe | Send Slack/email/PagerDuty alert |
| `create_incident_ticket` | safe | Create incident tracking ticket |
| `get_on_call_engineer` | safe | Current on-call and escalation chain |

### send_notification
```
Args:
  channel: str      — "slack", "email", "pagerduty", or "all"
  message: str      — Notification content
  severity: str     — "low", "medium", "high", "critical"
  service: str?     — Related service
  incident_id: str? — Related incident

Returns: { notification_id, delivered_to, recipients: [...] }
```

### create_incident_ticket
```
Args:
  title: str           — Short incident title
  description: str     — Detailed description
  priority: str        — P1 (15min SLA) | P2 (1hr) | P3 (4hr) | P4 (24hr)
  service: str?        — Affected service
  assigned_to: str?    — Assignee (default: on-call)

Returns: { ticket: { id, title, priority, assigned_to, sla_response_minutes } }
```

### get_on_call_engineer
```
Args:
  team: str? — Team filter (optional)

Returns: { current_rotation: { primary, secondary }, 
           escalation_chain: [...] }
```

---

## Risk Classification

| Level | Meaning | Agent Behavior |
|-------|---------|----------------|
| **safe** | Read-only or informational | Auto-execute |
| **risky** | Temporary impact, reversible | Execute with logging |
| **dangerous** | Production code/state change | Require human approval |

---

## Testing

```bash
# Generate mock data first
python -m backend.mock_data_generator --seed-all

# Test all servers
python -m tests.test_mcp_servers

# Test individual server with MCP Inspector
mcp dev mcp_servers/logs_server.py
mcp dev mcp_servers/metrics_server.py
mcp dev mcp_servers/infra_server.py
mcp dev mcp_servers/alert_server.py
```