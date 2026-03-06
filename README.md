<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Next.js-15-000000?style=for-the-badge&logo=next.js&logoColor=white" />
  <img src="https://img.shields.io/badge/LangGraph-1.0-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.134-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white" />
  <img src="https://img.shields.io/badge/MCP-Protocol-8B5CF6?style=for-the-badge" />
  <img src="https://img.shields.io/badge/A2A-Protocol-F59E0B?style=for-the-badge" />
</p>

<h1 align="center"> SentinelAI</h1>
<h3 align="center">Autonomous Multi-Agent DevOps Incident Response Platform</h3>

<p align="center">
  <em>Self-healing infrastructure powered by LangGraph agents, Model Context Protocol, and Agent-to-Agent communication.</em>
</p>

---

SentinelAI is an autonomous DevOps incident response platform that **monitors**, **diagnoses**, **plans**, and **remediates** infrastructure failures in real-time — without human intervention for safe actions, and with human-in-the-loop approval for risky ones.

Built on a **multi-agent architecture** using LangGraph state machines, it coordinates four specialized AI agents that communicate through the **A2A (Agent-to-Agent) Protocol** and interact with live infrastructure through **Model Context Protocol (MCP)** tool servers.

---

## Architecture

```
                      ┌──────────────────────────────────────────────────────────────────┐
                      │                    Command Center (Next.js)                      │
                      │        Dashboard · Incidents · Approvals · Chaos Lab · Safety    │
                      └─────────────────────────────┬────────────────────────────────────┘
                                                    │ REST API
                      ┌─────────────────────────────▼────────────────────────────────────┐
                      │                      FastAPI Backend                             │
                      │    Dashboard API · Approval API · Watcher Loop · Dev API         │
                      └──────┬──────────┬──────────────┬──────────────┬──────────────────┘
                             │          │              │              │
                             ▼          ▼              ▼              ▼
                        ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
                        │ Watcher │ │Diagnosti-│ │Strategist│ │ Executor │
                        │  Agent  │→│cian Agent│→│  Agent   │→│  Agent   │
                        └────┬────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘
                             │           │            │            │
                             │    ┌─────--────--┐     │            │
                             │    │  ChromaDB   │     │            │
                             │    │  RAG Store  │     │            │
                             │    └─────────────┘     │            │
                             │                        │            │
                             ▼                        ▼            ▼ 
                        ┌─────────────────────────────────────────────────┐
                        │              MCP Tool Servers (13 tools)        │
                        │  LogsMCP · MetricsMCP · InfraMCP · AlertMCP     │
                        └──────────────────────┬──────────────────────────┘
                                               │
                        ┌──────────────────────▼─────────────────────────────┐
                        │            Live Microservices                      │
                        │   user-service · payment-service · api-gateway     │
                        ├──────────────────────────────────────────────────  │
                        │  Prometheus · Grafana · Loki · Promtail · cAdvisor │ 
                        └────────────────────────────────────────────────────┘
```

---

## Multi-Agent System

### Agent Pipeline: `Watcher → Diagnostician → Strategist → Executor`

Each agent is a **LangGraph state machine** with typed state, conditional edges, and tool-calling nodes.

| Agent | Role | Key Technique |
|-------|------|--------------|
| **🔭 Watcher** | Monitors services via Prometheus/Loki, detects anomalies using LLM analysis of metrics + logs | LangGraph flow: `collect_metrics → collect_logs → analyze → decide → alert` |
| **🔬 Diagnostician** | Root-cause analysis with hypothesis generation, evidence gathering, and iterative refinement | **ReAct loop** with ChromaDB RAG for similar-incident retrieval |
| **📋 Strategist** | Generates risk-tiered remediation plans (safe/risky/dangerous), selects optimal plan, gates approvals | Multi-plan generation → Rank & Select → Approval gate → Execute safe actions |
| **⚡ Executor** | Dispatches MCP tool calls for approved actions; no LLM needed — pure dispatcher | Direct MCP calls via A2A task delegation |

### Always-On Watcher Loop

The Watcher runs as a **continuous background loop**, polling Prometheus every 15s (configurable). When anomalies persist for consecutive checks:
1. Triggers the full `Watcher → Diagnostician → Strategist` pipeline
2. Auto-executes safe remediations
3. Queues risky/dangerous actions for human approval
4. **Verifies remediation** post-action and auto-scales back when healthy

---

## MCP Tool Servers

SentinelAI uses **4 MCP servers** exposing **13 tools** that agents discover and call at runtime via the [Model Context Protocol](https://modelcontextprotocol.io/).

| Server | Tools | Purpose |
|--------|-------|---------|
| **LogsMCP** | `search_logs`, `get_recent_errors` | Log search and error aggregation via Loki |
| **MetricsMCP** | `get_current_metrics`, `get_metric_history`, `detect_anomaly` | Real-time metrics and anomaly detection via Prometheus |
| **InfraMCP** | `restart_service`, `scale_service`, `get_deployment_history` | Infrastructure actions via Docker API |
| **AlertMCP** | `send_notification`, `create_incident_ticket`, `get_on_call_engineer` | Alerting (Slack/Email/PagerDuty) and incident management |

### Risk Classification

| Level | Meaning | Agent Behavior |
|-------|---------|----------------|
| 🟢 **safe** | Read-only or informational | Auto-execute |
| 🟡 **risky** | Temporary impact, reversible | Execute with logging |
| 🔴 **dangerous** | Production state change | **Requires human approval** |

---

## A2A Protocol

Implements the [Agent-to-Agent Protocol](https://google.github.io/A2A/) (Linux Foundation standard) for inter-agent communication:

- **Agent Cards** — JSON descriptions of each agent's identity, skills, and capabilities
- **Task Lifecycle** — `submitted → working → completed/failed/awaiting_approval`
- **Skill Discovery** — Agents discover and delegate work to other agents by skill ID
- **A2A Client/Server** — Full client for task creation and server for task execution

---

## RAG Knowledge Base

The **Diagnostician** uses a ChromaDB vector store of past incidents for similar-incident retrieval:

- 12+ synthetic historical incidents across different failure types
- Vector embeddings via `sentence-transformers` for semantic search
- Incident types: `memory_leak`, `bad_deployment`, `api_timeout`, `cpu_spike`, `disk_full`, `ssl_expiry`, `connection_pool`, `data_consistency`
- Retrieved incidents inform hypothesis generation and remediation strategies

---

## Human-in-the-Loop Approvals

Actions classified as **risky** or **dangerous** require human approval before execution:

- Pending actions queued in PostgreSQL with full audit metadata
- **Approval Portal** in the dashboard for approve/reject with reasoning
- Concurrency-safe with per-action locking (prevents double-approval)
- Approved actions trigger the Executor and persist audit logs
- Full approval history for compliance and review

---

## Evaluation & Red Teaming

### DeepEval Evaluation Pipeline

Automated agent evaluation using [DeepEval](https://github.com/confident-ai/deepeval) metrics:

| Metric | What It Measures |
|--------|-----------------|
| **ToolCorrectness** | Did agents call the right tools? |
| **ArgumentCorrectness** | Did agents pass correct arguments? |
| **GEval (Diagnosis Quality)** | Accuracy and completeness of root cause analysis |
| **GEval (Plan Quality)** | Feasibility and risk-awareness of remediation plans |

### Red-Team Safety Testing

Adversarial test suite that validates agent robustness:

- **False Positive Resistance** — Does the Watcher avoid alerting on normal data?
- **Prompt Injection Resistance** — Can metrics/logs trick the agent into wrong decisions?
- **Severity Calibration** — Does the agent assign appropriate severity levels?
- **Guardrails Verification** — Are all safety mechanisms (approval gates, risk classification) in place?

---

## Command Center

The Next.js 15 dashboard provides real-time operational visibility:

| Page | Description |
|------|-------------|
| **Dashboard** | Live service health, incident stats, agent decision counts, activity feed |
| **Incidents** | Full incident list with severity, status, and drill-down to agent trace timeline |
| **Incident Detail** | Unified trace merging Watcher analysis, Diagnostician diagnosis, Strategist plans, and Executor results |
| **Approvals** | Pending action queue with approve/reject controls and decision history |
| **Chaos Lab** | Inject live faults (memory leak, CPU spike, network latency, kill service, cache failure) into running microservices |
| **Evaluations** | Agent performance metrics from the DeepEval pipeline |
| **Safety** | Red-team test results and guardrail status |

---

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Agents** | LangGraph, LangChain, Groq (Llama 3.1), CrewAI |
| **Backend** | Python 3.11, FastAPI, SQLAlchemy, Alembic, PostgreSQL |
| **Frontend** | Next.js 15, React, TypeScript, Tailwind CSS, Shadcn UI, Lucide Icons |
| **RAG** | ChromaDB, sentence-transformers, FAISS |
| **Protocols** | MCP (Model Context Protocol), A2A (Agent-to-Agent Protocol) |
| **Monitoring** | Prometheus, Grafana, Loki, Promtail, cAdvisor |
| **Evaluation** | DeepEval, Custom Red-Team Framework |
| **Infrastructure** | Docker Compose (12 services), Redis |
| **Services** | 3 mock microservices with Prometheus metrics, chaos endpoints, and structured JSON logging |

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Groq API key ([console.groq.com](https://console.groq.com))

### 1. Clone & Configure

```bash
git clone https://github.com/isakshay007/Sentinel-AI.git
cd Sentinel-AI
cp .env.example .env
# Set your GROQ_API_KEY in .env
```

### 2. Launch the Full Stack

```bash
docker-compose up --build
```

This starts **12 containers**: PostgreSQL, Redis, 3 microservices, backend, frontend, Prometheus, Grafana, Loki, Promtail, and cAdvisor. Migrations run automatically on backend startup.

### 3. Access the Platform

| Service | URL |
|---------|-----|
| **Dashboard** | [http://localhost:3000](http://localhost:3000) |
| **Backend API** | [http://localhost:8000](http://localhost:8000) |
| **API Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) |
| **Grafana** | [http://localhost:3001](http://localhost:3001) (admin/sentinel) |
| **Prometheus** | [http://localhost:9090](http://localhost:9090) |

### Local Development (without Docker)

```bash
# Terminal 1: Backend (migrations run automatically on startup)
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend && npm install && npm run dev

# Terminal 3: Seed RAG knowledge base
python -m rag.chroma_store --seed
```

---

##  Project Structure

```
Sentinel-AI/
├── agents/                  # LangGraph agent implementations
│   ├── watcher.py           #   Anomaly detection agent (LangGraph)
│   ├── diagnostician.py     #   Root cause analysis agent (ReAct + RAG)
│   ├── strategist.py        #   Remediation planning agent
│   ├── executor_crew.py     #   Action dispatch agent (MCP calls)
│   └── watcher_loop.py      #   Always-on monitoring loop
├── a2a/
│   └── protocol.py          # A2A protocol (Agent Cards, Tasks, Client/Server)
├── backend/
│   ├── main.py              # FastAPI app entrypoint
│   ├── dashboard_api.py     # Dashboard REST endpoints
│   ├── approval.py          # Human-in-the-loop approval system
│   ├── prometheus_client.py # Prometheus/Loki query client
│   ├── models.py            # SQLAlchemy models
│   └── alembic/             # Database migrations
├── frontend/                # Next.js 15 tactical dashboard
│   └── src/
│       ├── app/             # Pages: dashboard, incidents, approvals, chaos, safety
│       ├── components/      # UI: sidebar, terminal, fault injection dialog
│       └── contexts/        # React contexts: pipeline, fault injection, terminals
├── mcp_servers/             # Model Context Protocol tool servers
│   ├── logs_server.py       #   Log search via Loki
│   ├── metrics_server.py    #   Metrics via Prometheus
│   ├── infra_server.py      #   Infrastructure actions via Docker
│   └── alert_server.py      #   Notifications and incident tickets
├── rag/
│   └── chroma_store.py      # ChromaDB vector store for past incidents
├── evaluation/
│   ├── eval_pipeline.py     # DeepEval agent evaluation pipeline
│   └── red_team/            # Adversarial safety testing
├── services/                # Mock microservices with chaos endpoints
│   ├── user-service/        #   Flask app with Prometheus metrics
│   ├── payment-service/     #   Flask app with Prometheus metrics
│   └── api-gateway/         #   Flask app with Prometheus metrics
├── monitoring/              # Observability stack configs
│   ├── prometheus/          #   Prometheus config + alert rules
│   ├── grafana/             #   Grafana dashboards + datasources
│   ├── loki/                #   Loki config
│   └── promtail/            #   Promtail config
├── docker-compose.yml       # Full stack orchestration (12 services)
├── requirements.txt         # Python dependencies
└── docs/
    └── tools.md             # MCP tools reference
```



##  Running Tests

```bash
# Unit tests
pytest tests/

# Evaluation pipeline (requires running services)
python -m evaluation.eval_pipeline --scenarios memory_leak,cpu_spike

# Red-team safety tests
python -m evaluation.red_team.safety_runner

# MCP server testing with Inspector
mcp dev mcp_servers/metrics_server.py
```

---

<p align="center">
  <strong>Built for the mission-critical environment.</strong><br/>
  <sub>SentinelAI — Where autonomous agents meet production reliability.</sub>
</p>