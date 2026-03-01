import logging
import os

from fastapi import FastAPI

# Configure logging (uvicorn will override handler; this sets levels)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
from fastapi.middleware.cors import CORSMiddleware
from backend.approval import router as approval_router
from backend.dashboard_api import router as dashboard_router
from backend.dev_api import router as dev_router

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


@app.get("/health")
def health():
    return {"status": "healthy", "service": "sentinelai"}