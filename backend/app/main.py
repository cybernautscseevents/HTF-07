"""
AEGIS-Flow — FastAPI application entry point.

Registers API routers and provides the health endpoint.
Business logic lives in the service layer, not here.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.analysis import router as analysis_router
from backend.app.api.cases import router as cases_router
from backend.app.api.events import router as events_router

app = FastAPI(
    title="AEGIS-Flow",
    description="Temporal Fraud-Flow Intervention Engine",
    version="0.1.0",
)

# ── CORS Middleware ──────────────────────────────────────────────────────────

allowed_origins_env = os.getenv(
    "ALLOWED_ORIGINS",
    os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000",
    ),
)
allowed_origins = [
    origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if allowed_origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────

app.include_router(cases_router)
app.include_router(events_router)
app.include_router(analysis_router)


# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/health", tags=["ops"])
async def health_check() -> dict:
    """Lightweight liveness probe — confirms the server is running."""
    return {"status": "ok"}
