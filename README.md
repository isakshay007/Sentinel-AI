# SentinelAI
Autonomous DevOps Incident Response Platform

## Status: Foundation

## Quick Setup

| Service  | Port | Command |
|----------|------|---------|
| Backend  | 8000 | `uvicorn backend.main:app --reload --port 8000` |
| Frontend | 3000 | `cd frontend && npm run dev` |

1. Copy `.env.example` → `.env`, set `GROQ_API_KEY`, `DATABASE_URL`
2. Run `alembic -c backend/alembic.ini upgrade head`
3. Start backend and frontend (see table)
4. Open http://localhost:3000