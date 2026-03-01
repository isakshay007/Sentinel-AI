from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.approval import router as approval_router
from backend.dashboard_api import router as dashboard_router

app = FastAPI(title="SentinelAI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(approval_router)
app.include_router(dashboard_router)


@app.get("/health")
def health():
    return {"status": "healthy", "service": "sentinelai"}