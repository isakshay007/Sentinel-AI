# Gaps to Fix Before Building the Frontend

Validated against the current codebase. Fix in this order so the dashboard API and flows work correctly.

**Status:** All critical and high-priority items below have been implemented (see commit / diff). Run `alembic upgrade head` from the `backend` directory to add the `incident_id` column to `audit_logs` if your DB already exists.

---

## 1. **Critical: Run-scenario does not persist to DB**

**Evidence:** `backend/dashboard_api.py` line 286–301: `run_scenario()` calls only `run_watcher()`. It never writes to PostgreSQL.

**Impact:** Frontend triggers "Run scenario" → Watcher runs → API returns result, but no `Incident`, `AgentDecision`, or `AuditLog` rows are created. Dashboard stats and incident list stay empty (or show only seed data).

**Fix:** When the dashboard runs a scenario, run a pipeline that persists. Either:
- **Option A:** Change `POST /api/run-scenario/{scenario}` to run the full pipeline (Watcher → Diagnostician → Strategist), persist all phases (using `watcher_db`, `diagnostician_db`, `strategist_db`), and register pending actions with the approval API; or
- **Option B:** Keep run-scenario as Watcher-only but call `watcher_db.run_and_persist()` so at least Watcher results (incident + decision + audits) appear in the dashboard.

Recommendation: **Option A** so one action gives incidents, decisions, trace, and pending approvals.

---

## 2. **Critical: Pending approvals never reach the approval API**

**Evidence:** `agents/strategist.py` lines 324–339: `approval_gate` builds `pending_actions` with `approval_id`, but nothing calls `backend.approval.add_approval_request()`. `GET /api/approvals` reads from `_approval_store`, which is never populated by the pipeline.

**Impact:** Frontend cannot show or approve risky actions; approval list is always empty.

**Fix:**
- When the API runs the full pipeline (after Fix 1), after Strategist persists, for each `pending_actions` item call `add_approval_request(...)` (or a variant that accepts an existing `id` so the Strategist’s `approval_id` is used).
- In `backend/approval.py`, add support for registering with a given id (e.g. `add_approval_request(..., id=approval_id)`) so `POST /api/approve/{action_id}` matches the id the frontend got from the pipeline response.

---

## 3. **Critical: Agent trace shows wrong audits**

**Evidence:** `backend/dashboard_api.py` lines 149–154: `get_agent_trace(incident_id)` loads audits with:

```python
audits = db.query(AuditLog).order_by(AuditLog.timestamp.asc()).limit(100).all()
```

There is no filter by `incident_id`. `AuditLog` has no `incident_id` column (`backend/models.py` lines 39–47).

**Impact:** Every incident’s “trace” shows the same global audit entries; trace is not per-incident.

**Fix:**
- Add `incident_id = Column(String, nullable=True)` to `AuditLog` in `backend/models.py`.
- Add a migration (or ensure `Base.metadata.create_all` runs) so the column exists.
- In `watcher_db.py`, `diagnostician_db.py`, `strategist_db.py`, set `incident_id` when creating each `AuditLog` (use the run’s incident_id for that phase).
- In `get_agent_trace`, filter: `db.query(AuditLog).filter(AuditLog.incident_id == incident_id).order_by(...)`.

---

## 4. **High: Dashboard file paths depend on CWD**

**Evidence:** `backend/dashboard_api.py` lines 18–19:

```python
EVAL_DIR = Path("evaluation/results")
FIXTURES_DIR = Path("tests/fixtures")
```

These are relative to the process current working directory. If the server is started from `backend/` or another directory, these paths can be wrong and stats/eval/safety/service-health can fail or return empty.

**Fix:** Resolve paths relative to the project root (e.g. `Path(__file__).resolve().parent.parent` for repo root) and then join `evaluation/results` and `tests/fixtures`.

---

## 5. **High: seed_db imports will fail when run as module**

**Evidence:** `backend/seed_db.py` lines 19–20:

```python
from database import SessionLocal, engine
from models import Base, Incident, AuditLog
```

When run as `python -m backend.seed_db` from the project root, the package is `backend`; there is no top-level `database` or `models` module. Imports should be `from backend.database import ...` and `from backend.models import ...`.

**Fix:** Change to `from backend.database import SessionLocal, engine` and `from backend.models import Base, Incident, AuditLog` (and fix `mock_data_generator` import if needed).

---

## 6. **Medium: Safe default when eval/safety files are missing**

**Evidence:** `get_dashboard_stats()` and `get_safety_report()` use default scores when files are missing, but `get_eval_results()` and similar endpoints can raise or behave oddly if the directory doesn’t exist or is empty.

**Fix:** Use `EVAL_DIR.exists()` and handle missing/empty dirs so the API always returns a valid structure (e.g. empty list or default scores) instead of 500.

---

## Summary order of implementation

| Order | Fix | Blocks frontend? |
|-------|-----|-------------------|
| 1 | Run-scenario (or new endpoint) runs pipeline + persist + register approvals | Yes – no data for dashboard |
| 2 | Approval store wired (add_approval_request with optional id) | Yes – no pending approvals to show |
| 3 | AuditLog.incident_id + persist + filter in get_agent_trace | Yes – wrong trace per incident |
| 4 | Dashboard paths relative to project root | Yes – wrong/env-dependent data |
| 5 | seed_db backend imports | No – only affects seeding/scripts |
| 6 | Graceful handling of missing eval/safety files | No – avoids 500 in edge cases |

Implementing 1–4 before frontend work is strongly recommended; 5–6 are quick and reduce surprises.
