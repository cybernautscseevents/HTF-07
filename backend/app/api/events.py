"""
Event API routes.

POST /api/events          — ingest a single transaction event
POST /api/events/batch    — ingest an ordered batch of events
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from contracts.transaction import TransactionEvent

from backend.app.dependencies import get_event_service
from backend.app.services.case_service import EventService

router = APIRouter(prefix="/api/events", tags=["events"])


@router.post("", status_code=201)
async def ingest_event(
    request: Request,
    case_id: str = Query(..., description="Case to associate this event with."),
    svc: EventService = Depends(get_event_service),
) -> dict:
    """
    Ingest a single canonical TransactionEvent and associate it with a case.

    Uses ``model_validate_json`` because the canonical TransactionEvent
    uses ``strict=True``.
    """
    body = await request.body()
    try:
        event = TransactionEvent.model_validate_json(body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        stored = await svc.ingest_event(event, case_id)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        # Duplicate event_id
        raise HTTPException(status_code=409, detail=detail)

    return stored.model_dump(mode="json")


@router.post("/batch", status_code=201)
async def ingest_batch(
    request: Request,
    case_id: str = Query(..., description="Case to associate these events with."),
    svc: EventService = Depends(get_event_service),
) -> dict:
    """
    Ingest an ordered batch of canonical TransactionEvents.

    Expects a JSON array of TransactionEvent objects.
    Preserves insertion order.  Atomic: if any event fails validation
    or has a duplicate event_id, the entire batch is rejected.
    """
    body = await request.body()
    try:
        raw_list = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid JSON: {exc}")

    if not isinstance(raw_list, list):
        raise HTTPException(status_code=422, detail="Request body must be a JSON array.")

    events: list[TransactionEvent] = []
    for idx, item in enumerate(raw_list):
        try:
            ev = TransactionEvent.model_validate_json(json.dumps(item))
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"Event at index {idx}: {exc}"
            )
        events.append(ev)

    try:
        stored = await svc.ingest_batch(events, case_id)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=409, detail=detail)

    return {"accepted": len(stored), "event_ids": [e.event_id for e in stored]}
