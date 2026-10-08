"""
Repository abstractions for AEGIS-Flow persistence.

Defines the interface contracts that any persistence backend
(in-memory, PostgreSQL, etc.) must satisfy.  The API and service
layers depend only on these abstractions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from contracts.case import FraudCase
from contracts.transaction import TransactionEvent


class CaseRepository(ABC):
    """Abstract persistence interface for FraudCase objects."""

    @abstractmethod
    async def save(self, case: FraudCase) -> None:
        """Persist a case.  Raises ValueError if case_id already exists."""

    @abstractmethod
    async def get(self, case_id: str) -> FraudCase | None:
        """Return a case by ID, or None if not found."""

    @abstractmethod
    async def exists(self, case_id: str) -> bool:
        """Return True if a case with this ID exists."""

    @abstractmethod
    async def list_all(self) -> list[FraudCase]:
        """Return all stored cases (MVP only — no pagination)."""


class EventRepository(ABC):
    """Abstract persistence interface for TransactionEvent objects."""

    @abstractmethod
    async def save(self, event: TransactionEvent, case_id: str) -> None:
        """
        Persist a single event and associate it with a case.
        Raises ValueError if event_id already exists.
        """

    @abstractmethod
    async def save_batch(
        self, events: list[TransactionEvent], case_id: str
    ) -> None:
        """
        Persist a batch of events, preserving insertion order.
        Raises ValueError if any event_id already exists (no partial writes).
        """

    @abstractmethod
    async def get_by_event_id(self, event_id: str) -> TransactionEvent | None:
        """Return a single event by its event_id, or None."""

    @abstractmethod
    async def get_by_case_id(self, case_id: str) -> list[TransactionEvent]:
        """Return all events associated with a case, in insertion order."""

    @abstractmethod
    async def event_exists(self, event_id: str) -> bool:
        """Return True if an event with this ID exists."""
