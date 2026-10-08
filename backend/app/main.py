"""
AEGIS-Flow — FastAPI application entry point.

Registers API routers and provides the health endpoint.
Business logic lives in the service layer, not here.
"""

from fastapi import FastAPI

from backend.app.api.cases import router as cases_router
from backend.app.api.events import router as events_router

app = FastAPI(
    title="AEGIS-Flow",
    description="Temporal Fraud-Flow Intervention Engine",
    version="0.1.0",
)

# ── Routers ──────────────────────────────────────────────────────────────────

app.include_router(cases_router)
app.include_router(events_router)


# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/health", tags=["ops"])
async def health_check() -> dict:
    """Lightweight liveness probe — confirms the server is running."""
    return {"status": "ok"}
