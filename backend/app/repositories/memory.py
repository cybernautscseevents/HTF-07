"""
In-memory repository implementations for hackathon MVP.

Thread-safety note: these are single-process, single-event-loop stores.
Concurrency is handled by asyncio's cooperative scheduling — no locks
needed for the hackathon prototype.
"""

from __future__ import annotations

from contracts.case import FraudCase
from contracts.transaction import TransactionEvent

from backend.app.repositories.base import CaseRepository, EventRepository


class InMemoryCaseRepository(CaseRepository):
    """Dict-backed case store."""

    def __init__(self) -> None:
        self._cases: dict[str, FraudCase] = {}

    async def save(self, case: FraudCase) -> None:
        if case.case_id in self._cases:
            raise ValueError(f"Case '{case.case_id}' already exists.")
        self._cases[case.case_id] = case

    async def get(self, case_id: str) -> FraudCase | None:
        return self._cases.get(case_id)

    async def exists(self, case_id: str) -> bool:
        return case_id in self._cases

    async def list_all(self) -> list[FraudCase]:
        return list(self._cases.values())


class InMemoryEventRepository(EventRepository):
    """Dict-backed event store with case-association index."""

    def __init__(self) -> None:
        self._events: dict[str, TransactionEvent] = {}
        # case_id → ordered list of event_ids (preserves ingestion order)
        self._case_index: dict[str, list[str]] = {}

    async def save(self, event: TransactionEvent, case_id: str) -> None:
        if event.event_id in self._events:
            raise ValueError(f"Event '{event.event_id}' already exists.")
        self._events[event.event_id] = event
        self._case_index.setdefault(case_id, []).append(event.event_id)

    async def save_batch(
        self, events: list[TransactionEvent], case_id: str
    ) -> None:
        # Pre-validate: no duplicates in batch or against existing store.
        for ev in events:
            if ev.event_id in self._events:
                raise ValueError(f"Event '{ev.event_id}' already exists.")
        seen: set[str] = set()
        for ev in events:
            if ev.event_id in seen:
                raise ValueError(
                    f"Duplicate event_id '{ev.event_id}' within batch."
                )
            seen.add(ev.event_id)

        # All validations passed — commit atomically.
        for ev in events:
            self._events[ev.event_id] = ev
            self._case_index.setdefault(case_id, []).append(ev.event_id)

    async def get_by_event_id(self, event_id: str) -> TransactionEvent | None:
        return self._events.get(event_id)

    async def get_by_case_id(self, case_id: str) -> list[TransactionEvent]:
        ids = self._case_index.get(case_id, [])
        return [self._events[eid] for eid in ids]

    async def event_exists(self, event_id: str) -> bool:
        return event_id in self._events
