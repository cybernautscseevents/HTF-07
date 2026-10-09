"""
Case API routes.

POST /api/cases          — create a new fraud case
GET  /api/cases/{id}     — retrieve a case by ID
GET  /api/cases/{id}/graph    — temporal graph stub
GET  /api/cases/{id}/timeline — events ordered by occurred_at
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from contracts.case import FraudCase

from backend.app.dependencies import get_case_service
from backend.app.services.case_service import CaseService

router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.post("", status_code=201)
async def create_case(
    request: Request,
    svc: CaseService = Depends(get_case_service),
) -> dict:
    """
    Create a new fraud case from canonical FraudCase JSON.

    We parse the raw JSON body with ``model_validate_json`` because the
    canonical FraudCase uses ``strict=True`` — Pydantic's strict mode
    rejects datetime strings when validating from a Python dict, but
    accepts them when validating from raw JSON bytes.
    """
    body = await request.body()
    try:
        case = FraudCase.model_validate_json(body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        created = await svc.create_case(case)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return created.model_dump(mode="json")


@router.get("")
async def list_cases(
    svc: CaseService = Depends(get_case_service),
) -> list[dict]:
    """List all stored fraud cases."""
    cases = await svc.list_cases()
    return [c.model_dump(mode="json") for c in cases]


@router.get("/{case_id}")
async def get_case(
    case_id: str,
    svc: CaseService = Depends(get_case_service),
) -> dict:
    """Retrieve a fraud case by ID."""
    case = await svc.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
    return case.model_dump(mode="json")


@router.get("/{case_id}/timeline")
async def get_timeline(
    case_id: str,
    svc: CaseService = Depends(get_case_service),
) -> list[dict]:
    """Return events for a case ordered by occurred_at."""
    try:
        events = await svc.get_timeline(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return [ev.model_dump(mode="json") for ev in events]


@router.get("/{case_id}/graph")
async def get_graph(
    case_id: str,
    svc: CaseService = Depends(get_case_service),
) -> dict:
    """
    Return the temporal transaction graph for a case.

    Currently returns a stub node/edge manifest derived from stored
    events.  Will delegate to the graph engine service when available.
    """
    try:
        return await svc.get_graph(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
