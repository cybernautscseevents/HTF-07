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
from backend.app.services.case_graph_registry import CaseGraphRegistry


class CaseService:
    """Orchestrates fraud-case operations."""

    def __init__(
        self,
        case_repo: CaseRepository,
        event_repo: EventRepository,
        graph_registry: CaseGraphRegistry,
    ) -> None:
        self._cases = case_repo
        self._events = event_repo
        self._graphs = graph_registry

    async def create_case(self, case: FraudCase) -> FraudCase:
        """Persist a new case.  Raises ValueError on duplicate case_id."""
        await self._cases.save(case)
        self._graphs.get_or_create(case.case_id)
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
        Return a serializable representation of the actual temporal graph.
        """
        if not await self._cases.exists(case_id):
            raise ValueError(f"Case '{case_id}' not found.")

        graph = self._graphs.graph(case_id)
        if graph is None:
            self._graphs.add_events(
                case_id, await self._events.get_by_case_id(case_id)
            )
            graph = self._graphs.graph(case_id)
            assert graph is not None

        edges = [
            {
                "event_id": edge.event_id,
                "source": edge.sender_id,
                "target": edge.receiver_id,
                "amount_minor_units": edge.amount_minor_units,
                "currency": edge.currency,
                "occurred_at": edge.occurred_at.isoformat(),
                "status": edge.status.value,
            }
            for edge in graph.events_between(active_only=False)
        ]

        return {
            "case_id": case_id,
            "node_count": graph.node_count,
            "edge_count": graph.edge_count,
            "nodes": sorted(graph.accounts),
            "edges": edges,
        }


class EventService:
    """Orchestrates transaction-event ingestion."""

    def __init__(
        self,
        case_repo: CaseRepository,
        event_repo: EventRepository,
        graph_registry: CaseGraphRegistry,
    ) -> None:
        self._cases = case_repo
        self._events = event_repo
        self._graphs = graph_registry

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
        self._graphs.add_event(case_id, event)
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
        self._graphs.add_events(case_id, events)
        return events
