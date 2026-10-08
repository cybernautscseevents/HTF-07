"""
AEGIS-Flow — FastAPI application entry point.

Provides a minimal health endpoint for environment verification.
Business logic, database models, and ML pipelines are NOT implemented here.
"""

from fastapi import FastAPI

app = FastAPI(
    title="AEGIS-Flow",
    description="Temporal Fraud-Flow Intervention Engine",
    version="0.1.0",
)


@app.get("/health", tags=["ops"])
async def health_check() -> dict:
    """Lightweight liveness probe — confirms the server is running."""
    return {"status": "ok"}
