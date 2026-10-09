"""Investigation Analysis API routes.

Endpoint: POST /api/cases/{case_id}/analyze
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.schemas.analysis import (
    InvestigationAnalysisRequest,
    InvestigationAnalysisResponse,
)
from backend.app.dependencies import get_investigation_orchestrator
from backend.app.services.investigation_orchestrator import (
    CaseNotFoundError,
    EmptyCaseError,
    InvestigationOrchestrator,
)

router = APIRouter(prefix="/api/cases", tags=["analysis"])


@router.post(
    "/{case_id}/analyze",
    response_model=InvestigationAnalysisResponse,
    status_code=200,
    summary="Run end-to-end fraud investigation analysis",
    description=(
        "Executes graph construction, deterministic taint propagation, supervised risk assessment, "
        "next-hop prediction, forecast-aware trajectory simulation, temporal chokepoint min-cut search, "
        "and Pareto intervention optimization."
    ),
)
async def analyze_case(
    case_id: str,
    request: InvestigationAnalysisRequest,
    orchestrator: InvestigationOrchestrator = Depends(get_investigation_orchestrator),
) -> InvestigationAnalysisResponse:
    """Analyze a case given explicit simulation timestamp, fraud seeds, and parameters."""
    try:
        return await orchestrator.analyze(case_id, request)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (EmptyCaseError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal investigation failure: {exc}")
