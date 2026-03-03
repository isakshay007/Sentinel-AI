import logging
import os
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.approval import router as approval_router
from backend.dashboard_api import router as dashboard_router
from backend.dev_api import router as dev_router

# Configure logging (uvicorn will override handler; this sets levels)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

app = FastAPI(title="SentinelAI", version="0.1.0")

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
    """Start background watcher loop if enabled."""
    from agents.watcher_loop import watcher_loop

    if os.getenv("WATCHER_ENABLED", "1") != "1":
        logging.getLogger(__name__).info("WatcherLoop disabled via WATCHER_ENABLED=0")
        return

    async def _runner():
        log = logging.getLogger(__name__)
        while True:
            try:
                await watcher_loop()
            except Exception as e:
                log.exception("WatcherLoop crashed: %s — restarting in 10s", e)
                await asyncio.sleep(10)

    asyncio.create_task(_runner())


@app.get("/health")
def health():
    return {"status": "healthy", "service": "sentinelai"}