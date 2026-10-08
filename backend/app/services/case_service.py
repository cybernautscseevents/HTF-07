"""
Service layer — mediates between API routes and repositories.

Responsibilities:
- Validate business rules that go beyond Pydantic schema validation
- Coordinate repository writes
- Provide hook points for the temporal graph service (when available)
"""

from __future__ import annotations

from contracts.case import FraudCase
from contracts.transaction import TransactionEvent

from backend.app.repositories.base import CaseRepository, EventRepository


class CaseService:
    """Orchestrates fraud-case operations."""

    def __init__(
        self,
        case_repo: CaseRepository,
        event_repo: EventRepository,
    ) -> None:
        self._cases = case_repo
        self._events = event_repo

    async def create_case(self, case: FraudCase) -> FraudCase:
        """Persist a new case.  Raises ValueError on duplicate case_id."""
        await self._cases.save(case)
        return case

    async def get_case(self, case_id: str) -> FraudCase | None:
        return await self._cases.get(case_id)

    async def get_timeline(self, case_id: str) -> list[TransactionEvent]:
        """
        Return events for a case ordered by occurred_at (ascending).
        Raises ValueError if the case does not exist.
        """
        if not await self._cases.exists(case_id):
            raise ValueError(f"Case '{case_id}' not found.")
        events = await self._events.get_by_case_id(case_id)
        return sorted(events, key=lambda e: e.occurred_at)

    async def get_graph(self, case_id: str) -> dict:
        """
        Return the temporal graph for a case.

        Currently returns a stub structure.  When the graph service is
        available this will delegate to it rather than computing anything
        inside the API layer.
        """
        if not await self._cases.exists(case_id):
            raise ValueError(f"Case '{case_id}' not found.")

        events = await self._events.get_by_case_id(case_id)

        # Build a minimal node/edge manifest from stored events.
        # The real graph topology will come from the graph engine.
        nodes: set[str] = set()
        edges: list[dict] = []
        for ev in sorted(events, key=lambda e: e.occurred_at):
            nodes.add(ev.sender.account_id)
            nodes.add(ev.receiver.account_id)
            edges.append(
                {
                    "event_id": ev.event_id,
                    "source": ev.sender.account_id,
                    "target": ev.receiver.account_id,
                    "amount_minor_units": ev.amount_minor_units,
                    "currency": ev.currency,
                    "occurred_at": ev.occurred_at.isoformat(),
                }
            )

        return {
            "case_id": case_id,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": sorted(nodes),
            "edges": edges,
        }


class EventService:
    """Orchestrates transaction-event ingestion."""

    def __init__(
        self,
        case_repo: CaseRepository,
        event_repo: EventRepository,
    ) -> None:
        self._cases = case_repo
        self._events = event_repo

    async def ingest_event(
        self, event: TransactionEvent, case_id: str
    ) -> TransactionEvent:
        """
        Validate, persist, and associate a single event with a case.
        Raises ValueError if the case doesn't exist or event_id is a duplicate.
        """
        if not await self._cases.exists(case_id):
            raise ValueError(f"Case '{case_id}' not found.")
        # Duplicate event_id check is enforced inside the repository.
        await self._events.save(event, case_id)
        # TODO: forward to temporal graph service when available.
        return event

    async def ingest_batch(
        self, events: list[TransactionEvent], case_id: str
    ) -> list[TransactionEvent]:
        """
        Validate and persist a batch of events in order.
        Raises ValueError if the case doesn't exist or any event_id is a duplicate.
        """
        if not await self._cases.exists(case_id):
            raise ValueError(f"Case '{case_id}' not found.")
        await self._events.save_batch(events, case_id)
        # TODO: forward batch to temporal graph service when available.
        return events
