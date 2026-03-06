import logging
import os
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from backend.limiter import limiter
from backend.approval import router as approval_router
from backend.dashboard_api import router as dashboard_router
from backend.dev_api import router as dev_router

# Configure logging (uvicorn will override handler; this sets levels)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

app = FastAPI(title="SentinelAI", version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS: use CORS_ORIGINS env (comma-separated) or allow all for dev
_cors_origins = os.getenv("CORS_ORIGINS", "*")
origins = [o.strip() for o in _cors_origins.split(",")] if _cors_origins else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(approval_router)
app.include_router(dashboard_router)

# Dev router only when SENTINEL_DEV_MODE=1 (default: disabled for production)
if os.getenv("SENTINEL_DEV_MODE", "0") == "1":
    app.include_router(dev_router)


@app.on_event("startup")
async def startup_event() -> None:
    """Run migrations, then start background watcher loop if enabled."""
    log = logging.getLogger(__name__)
    from backend.startup import run_migrations
    if run_migrations():
        log.info("Database migrations applied")
    else:
        log.warning("Migrations skipped or failed — tables may be missing")

    if os.getenv("WATCHER_ENABLED", "1") != "1":
        log.info("WatcherLoop disabled via WATCHER_ENABLED=0")
        return

    from agents.watcher_loop import watcher_loop

    async def _runner():
        while True:
            try:
                await watcher_loop()
            except Exception as e:
                log.exception("WatcherLoop crashed: %s — restarting in 10s", e)
                await asyncio.sleep(10)

    asyncio.create_task(_runner())


@app.get("/health")
def health():
    """Basic liveness — always returns 200 if the process is up."""
    return {"status": "healthy", "service": "sentinelai"}


@app.get("/health/ready")
def health_ready():
    """
    Readiness check — verifies Postgres, Redis, and Prometheus are reachable.
    Returns 200 if all dependencies are healthy, 503 otherwise.
    """
    import httpx
    import redis as redis_lib
    from sqlalchemy import text
    from fastapi.responses import JSONResponse

    results = {}
    all_ok = True

    # Postgres
    try:
        from backend.database import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        results["postgres"] = "ok"
    except Exception as e:
        results["postgres"] = f"error: {str(e)[:80]}"
        all_ok = False

    # Redis (optional — backend may work without it in minimal mode)
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    try:
        r = redis_lib.Redis.from_url(redis_url, socket_timeout=2, socket_connect_timeout=2)
        r.ping()
        r.close()
        results["redis"] = "ok"
    except Exception as e:
        results["redis"] = f"error: {str(e)[:80]}"
        # Redis is used by services; backend uses it indirectly. Don't fail ready for Redis.
        # all_ok = False

    # Prometheus (optional for readiness — watcher needs it)
    prom_url = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{prom_url}/-/healthy")
            if resp.status_code == 200:
                results["prometheus"] = "ok"
            else:
                results["prometheus"] = f"status {resp.status_code}"
                all_ok = False
    except Exception as e:
        results["prometheus"] = f"error: {str(e)[:80]}"
        # Prometheus optional for readiness (required for full watcher functionality)

    if all_ok:
        return {"status": "ready", "checks": results}
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "checks": results},
    )