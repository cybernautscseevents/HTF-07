"""
Dependency wiring for FastAPI.

Provides singleton repository and service instances via FastAPI's
dependency injection system.  Swap InMemory* for Postgres* when the
database layer is ready — no API code changes needed.
"""

from __future__ import annotations

from backend.app.repositories.memory import (
    InMemoryCaseRepository,
    InMemoryEventRepository,
)
from backend.app.services.case_graph_registry import CaseGraphRegistry
from backend.app.services.case_service import CaseService, EventService
from backend.app.services.investigation_orchestrator import InvestigationOrchestrator

# ── Singleton repositories (process-lifetime) ────────────────────────────────

_case_repo = InMemoryCaseRepository()
_event_repo = InMemoryEventRepository()
_case_graph_registry = CaseGraphRegistry()

# ── Singleton services ───────────────────────────────────────────────────────

_case_service = CaseService(
    case_repo=_case_repo,
    event_repo=_event_repo,
    graph_registry=_case_graph_registry,
)
_event_service = EventService(
    case_repo=_case_repo,
    event_repo=_event_repo,
    graph_registry=_case_graph_registry,
)
_investigation_orchestrator = InvestigationOrchestrator(
    case_repo=_case_repo,
    event_repo=_event_repo,
    graph_registry=_case_graph_registry,
)


def get_case_service() -> CaseService:
    """FastAPI dependency — returns the CaseService singleton."""
    return _case_service


def get_event_service() -> EventService:
    """FastAPI dependency — returns the EventService singleton."""
    return _event_service


def get_case_graph_registry() -> CaseGraphRegistry:
    """FastAPI dependency — returns the process-lifetime graph registry."""
    return _case_graph_registry


def get_investigation_orchestrator() -> InvestigationOrchestrator:
    """FastAPI dependency — returns the InvestigationOrchestrator singleton."""
    return _investigation_orchestrator


def reset_repositories() -> None:
    """
    Reset all in-memory state.  Used by tests only.

    This replaces the internal stores of the existing singletons so that
    service references remain valid.
    """
    global _case_repo, _event_repo, _case_graph_registry, _case_service, _event_service, _investigation_orchestrator
    _case_repo = InMemoryCaseRepository()
    _event_repo = InMemoryEventRepository()
    _case_graph_registry = CaseGraphRegistry()
    _case_service = CaseService(
        case_repo=_case_repo,
        event_repo=_event_repo,
        graph_registry=_case_graph_registry,
    )
    _event_service = EventService(
        case_repo=_case_repo,
        event_repo=_event_repo,
        graph_registry=_case_graph_registry,
    )
    _investigation_orchestrator = InvestigationOrchestrator(
        case_repo=_case_repo,
        event_repo=_event_repo,
        graph_registry=_case_graph_registry,
    )
