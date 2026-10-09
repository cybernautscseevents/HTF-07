"""Immutable data models for temporal chokepoint search and minimum-cut analysis.

All model classes are frozen dataclasses. Money fields use exact integer
paise / minor units.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum, unique
from typing import Sequence

from backend.app.counterfactual.models import InterventionCandidate, InterventionType


@unique
class ChokepointStatus(StrEnum):
    """Execution status of the temporal chokepoint search."""

    OPTIMAL_CUT_FOUND = "optimal_cut_found"
    NO_PATH_EXISTS = "no_path_exists"
    NO_FEASIBLE_CUT = "no_feasible_cut"
    INVALID_INPUT = "invalid_input"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass(frozen=True, slots=True)
class ChokepointSearchConfig:
    """Configuration limits and parameters for bounded chokepoint search."""

    max_active_events: int = 10_000
    max_expanded_vertices: int = 50_000
    max_expanded_arcs: int = 100_000
    max_paths_to_verify: int = 1_000
    allow_zero_cost: bool = True
    verify_cut: bool = True

    def __post_init__(self) -> None:
        if self.max_active_events <= 0:
            raise ValueError("max_active_events must be strictly positive.")
        if self.max_expanded_vertices <= 0:
            raise ValueError("max_expanded_vertices must be strictly positive.")
        if self.max_expanded_arcs <= 0:
            raise ValueError("max_expanded_arcs must be strictly positive.")
        if self.max_paths_to_verify <= 0:
            raise ValueError("max_paths_to_verify must be strictly positive.")


@dataclass(frozen=True, slots=True)
class TemporalCutEdge:
    """A single transaction edge selected as part of the temporal minimum cut."""

    event_id: str
    transaction_id: str
    sender_account_id: str
    receiver_account_id: str
    amount_minor_units: int
    occurred_at: datetime
    estimated_legitimate_collateral_minor_units: int
    encoded_capacity: int
    is_forecast: bool = False

    def to_candidate(self) -> InterventionCandidate:
        """Convert this cut edge to an authoritative EDGE_HOLD candidate."""
        return InterventionCandidate(
            intervention_type=InterventionType.EDGE_HOLD,
            target_event_id=self.event_id,
        )


@dataclass(frozen=True, slots=True)
class ChokepointExplanation:
    """Structured, deterministic explanation of the chokepoint search result."""

    summary: str
    sources_analyzed: tuple[str, ...]
    sinks_targeted: tuple[str, ...]
    cut_edge_ids: tuple[str, ...]
    cost_minimality_rationale: str
    per_edge_collateral: tuple[tuple[str, int], ...]
    complete_cut_disconnects_all_paths: bool
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChokepointDiagnostics:
    """Operational statistics for auditability and complexity monitoring."""

    input_active_event_count: int
    eligible_cuttable_edge_count: int
    expanded_vertex_count: int
    expanded_arc_count: int
    initial_path_count: int
    residual_path_count: int
    runtime_ms: float
    pruning_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChokepointSearchResult:
    """Complete deterministic result of the temporal chokepoint search."""

    status: ChokepointStatus
    source_account_ids: tuple[str, ...]
    sink_account_ids: tuple[str, ...]
    cut_edges: tuple[TemporalCutEdge, ...]
    cut_size: int
    total_encoded_cut_cost: int
    total_estimated_legitimate_collateral_minor_units: int
    is_cut_verified: bool
    explanation: ChokepointExplanation
    diagnostics: ChokepointDiagnostics
    candidates: tuple[InterventionCandidate, ...]

    @property
    def cut_event_ids(self) -> tuple[str, ...]:
        """IDs of transaction events comprising the temporal cut."""
        return tuple(edge.event_id for edge in self.cut_edges)

    @property
    def is_feasible(self) -> bool:
        """Whether a feasible temporal cut was found separating sources from sinks."""
        return self.status == ChokepointStatus.OPTIMAL_CUT_FOUND
