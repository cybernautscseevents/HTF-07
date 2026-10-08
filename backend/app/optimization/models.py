"""Immutable models for counterfactual intervention optimization."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from backend.app.counterfactual.models import (
    CounterfactualResult,
    InterventionCandidate,
)


def candidate_sort_key(candidate: InterventionCandidate) -> tuple[str, str, str]:
    """Return the canonical ordering key for an intervention candidate."""
    return (
        candidate.intervention_type.value,
        candidate.target_account_id or "",
        candidate.target_event_id or "",
    )


@dataclass(frozen=True, slots=True)
class OptimizationConstraints:
    """Hard policy limits applied before Pareto ranking."""

    minimum_required_illicit_recovery: int = 0
    maximum_legitimate_capital_affected: int | None = None
    maximum_affected_accounts: int | None = None
    maximum_affected_edges: int | None = None
    maximum_interventions: int = 1
    minimum_provenance_confidence: float | None = None

    def __post_init__(self) -> None:
        if self.minimum_required_illicit_recovery < 0:
            raise ValueError("minimum_required_illicit_recovery must be non-negative.")
        for name in (
            "maximum_legitimate_capital_affected",
            "maximum_affected_accounts",
            "maximum_affected_edges",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative when provided.")
        if self.maximum_interventions < 1:
            raise ValueError("maximum_interventions must be at least one.")
        if self.minimum_provenance_confidence is not None and not (
            0.0 <= self.minimum_provenance_confidence <= 1.0
        ):
            raise ValueError("minimum_provenance_confidence must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class InterventionEvaluation:
    """One candidate's simulation, policy decision, and derived efficiency."""

    candidate: InterventionCandidate
    result: CounterfactualResult
    feasible: bool
    constraint_violations: tuple[str, ...]
    recovery_efficiency: Decimal
    pareto_rank: int | None = None
    dominated_by_intervention_ids: tuple[str, ...] = ()

    @property
    def intervention_id(self) -> str:
        return self.result.intervention_id


@dataclass(frozen=True, slots=True)
class CandidateComparison:
    """Deterministic explanation of why a competing candidate ranked lower."""

    intervention_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class OptimizationExplanation:
    """Structured, deterministic recommendation evidence."""

    recommendation_reason: str
    illicit_capital_intercepted: int
    legitimate_capital_affected: int
    recovery_efficiency: Decimal | None
    competing_candidates: tuple[CandidateComparison, ...]
    binding_constraints: tuple[str, ...]
    provenance_confidence: float | None


@dataclass(frozen=True, slots=True)
class ParetoFrontier:
    """Feasible candidates partitioned into efficient and dominated sets."""

    non_dominated: tuple[InterventionEvaluation, ...]
    dominated: tuple[InterventionEvaluation, ...]

    @property
    def size(self) -> int:
        return len(self.non_dominated)


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    """Complete deterministic output of one optimization run."""

    constraints: OptimizationConstraints
    evaluations: tuple[InterventionEvaluation, ...]
    feasible_evaluations: tuple[InterventionEvaluation, ...]
    infeasible_evaluations: tuple[InterventionEvaluation, ...]
    pareto_frontier: ParetoFrontier
    selected_evaluation: InterventionEvaluation | None
    explanation: OptimizationExplanation

    @property
    def selected_candidate(self) -> InterventionCandidate | None:
        if self.selected_evaluation is None:
            return None
        return self.selected_evaluation.candidate

    @property
    def dominated_candidates(self) -> tuple[InterventionEvaluation, ...]:
        return self.pareto_frontier.dominated
