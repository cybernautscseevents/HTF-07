"""Deterministic multi-objective intervention optimizer."""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime
from typing import Protocol

from backend.app.counterfactual.models import (
    CounterfactualResult,
    InterventionCandidate,
)
from backend.app.counterfactual.simulator import CounterfactualSimulator
from backend.app.optimization.models import (
    CandidateComparison,
    InterventionEvaluation,
    OptimizationConstraints,
    OptimizationExplanation,
    OptimizationResult,
    ParetoFrontier,
    candidate_sort_key,
)
from backend.app.optimization.policy import check_constraints


class CounterfactualEvaluator(Protocol):
    """Evaluator abstraction for observed or future forecast-aware worlds."""

    def evaluate(
        self, candidate: InterventionCandidate, simulation_timestamp: datetime
    ) -> CounterfactualResult:
        """Evaluate one candidate at one point in time."""


class ObservedFutureCounterfactualEvaluator:
    """Adapter from the authoritative observed-future simulator to the protocol."""

    def __init__(self, simulator: CounterfactualSimulator) -> None:
        self._simulator = simulator

    def evaluate(
        self, candidate: InterventionCandidate, simulation_timestamp: datetime
    ) -> CounterfactualResult:
        return self._simulator.simulate(candidate, simulation_timestamp)


def recovery_efficiency(intercepted: int, collateral: int) -> Decimal:
    """Return intercepted illicit capital per unit of legitimate collateral."""
    if intercepted < 0 or collateral < 0:
        raise ValueError("Capital values must be non-negative.")
    return Decimal(intercepted) / Decimal(max(1, collateral))


class MultiObjectiveInterventionOptimizer:
    """Evaluate single interventions and select a feasible Pareto-efficient one."""

    def __init__(self, evaluator: CounterfactualEvaluator) -> None:
        self._evaluator = evaluator

    def optimize(
        self,
        candidates: list[InterventionCandidate] | tuple[InterventionCandidate, ...],
        simulation_timestamp: datetime,
        constraints: OptimizationConstraints | None = None,
    ) -> OptimizationResult:
        if simulation_timestamp.tzinfo is None:
            raise ValueError("simulation_timestamp must be timezone-aware.")
        policy = constraints or OptimizationConstraints()

        unique_candidates = sorted(set(candidates), key=candidate_sort_key)
        evaluations = tuple(
            self._evaluate(candidate, simulation_timestamp, policy)
            for candidate in unique_candidates
        )
        feasible = tuple(e for e in evaluations if e.feasible)
        infeasible = tuple(e for e in evaluations if not e.feasible)
        frontier = self._build_frontier(feasible)
        selected = self._select(frontier.non_dominated)
        evaluations = self._with_ranks(evaluations, frontier)
        feasible = tuple(e for e in evaluations if e.feasible)
        infeasible = tuple(e for e in evaluations if not e.feasible)
        frontier = ParetoFrontier(
            non_dominated=tuple(e for e in evaluations if e.intervention_id in {
                item.intervention_id for item in frontier.non_dominated
            }),
            dominated=tuple(e for e in evaluations if e.intervention_id in {
                item.intervention_id for item in frontier.dominated
            }),
        )
        selected = next(
            (e for e in frontier.non_dominated
             if selected is not None and e.intervention_id == selected.intervention_id),
            None,
        )
        return OptimizationResult(
            constraints=policy,
            evaluations=evaluations,
            feasible_evaluations=feasible,
            infeasible_evaluations=infeasible,
            pareto_frontier=frontier,
            selected_evaluation=selected,
            explanation=self._explanation(selected, frontier, infeasible, policy),
        )

    def _evaluate(
        self,
        candidate: InterventionCandidate,
        timestamp: datetime,
        constraints: OptimizationConstraints,
    ) -> InterventionEvaluation:
        result = self._evaluator.evaluate(candidate, timestamp)
        violations = check_constraints(result, constraints)
        return InterventionEvaluation(
            candidate=candidate,
            result=result,
            feasible=not violations,
            constraint_violations=violations,
            recovery_efficiency=recovery_efficiency(
                result.modeled_tainted_capital_intercepted,
                result.modeled_legitimate_capital_affected,
            ),
        )

    @staticmethod
    def _dominates(
        left: InterventionEvaluation, right: InterventionEvaluation
    ) -> bool:
        left_values = (
            left.result.modeled_tainted_capital_intercepted,
            -left.result.modeled_legitimate_capital_affected,
            -left.result.number_of_affected_accounts,
            -left.result.number_of_affected_edges,
        )
        right_values = (
            right.result.modeled_tainted_capital_intercepted,
            -right.result.modeled_legitimate_capital_affected,
            -right.result.number_of_affected_accounts,
            -right.result.number_of_affected_edges,
        )
        return (
            all(a >= b for a, b in zip(left_values, right_values))
            and any(a > b for a, b in zip(left_values, right_values))
        )

    @classmethod
    def _build_frontier(
        cls, evaluations: tuple[InterventionEvaluation, ...]
    ) -> ParetoFrontier:
        non_dominated: list[InterventionEvaluation] = []
        dominated: list[InterventionEvaluation] = []
        for candidate in evaluations:
            if any(cls._dominates(other, candidate) for other in evaluations):
                dominated.append(candidate)
            else:
                non_dominated.append(candidate)
        return ParetoFrontier(tuple(non_dominated), tuple(dominated))

    @staticmethod
    def _select(
        evaluations: tuple[InterventionEvaluation, ...],
    ) -> InterventionEvaluation | None:
        if not evaluations:
            return None
        return min(
            evaluations,
            key=lambda e: (
                -e.result.modeled_tainted_capital_intercepted,
                e.result.modeled_legitimate_capital_affected,
                -e.recovery_efficiency,
                e.result.number_of_affected_accounts,
                e.result.number_of_affected_edges,
                e.intervention_id,
            ),
        )

    @classmethod
    def _with_ranks(
        cls,
        evaluations: tuple[InterventionEvaluation, ...],
        frontier: ParetoFrontier,
    ) -> tuple[InterventionEvaluation, ...]:
        frontier_ids = {e.intervention_id for e in frontier.non_dominated}
        dominated_ids = {e.intervention_id for e in frontier.dominated}
        return tuple(
            InterventionEvaluation(
                candidate=e.candidate,
                result=e.result,
                feasible=e.feasible,
                constraint_violations=e.constraint_violations,
                recovery_efficiency=e.recovery_efficiency,
                pareto_rank=0 if e.intervention_id in frontier_ids else (
                    1 if e.intervention_id in dominated_ids else None
                ),
                dominated_by_intervention_ids=tuple(
                    sorted(
                        other.intervention_id
                        for other in frontier.non_dominated
                        if cls._dominates(other, e)
                    )
                ),
            )
            for e in evaluations
        )

    @staticmethod
    def _explanation(
        selected: InterventionEvaluation | None,
        frontier: ParetoFrontier,
        infeasible: tuple[InterventionEvaluation, ...],
        constraints: OptimizationConstraints,
    ) -> OptimizationExplanation:
        if selected is None:
            comparisons = tuple(
                CandidateComparison(
                    e.intervention_id,
                    "infeasible: " + ", ".join(e.constraint_violations),
                )
                for e in infeasible
            )
            return OptimizationExplanation(
                recommendation_reason="No feasible intervention satisfies all hard policy constraints.",
                illicit_capital_intercepted=0,
                legitimate_capital_affected=0,
                recovery_efficiency=None,
                competing_candidates=comparisons,
                binding_constraints=(),
                provenance_confidence=None,
            )

        comparisons = tuple(
            [
                CandidateComparison(
                    e.intervention_id,
                    "dominated on one or more primary objectives",
                )
                for e in frontier.dominated
            ]
            + [
                CandidateComparison(
                    e.intervention_id,
                    "Pareto-efficient but ranked lower by deterministic tie-breaking",
                )
                for e in frontier.non_dominated
                if e.intervention_id != selected.intervention_id
            ]
            + [
                CandidateComparison(
                    e.intervention_id,
                    "infeasible: " + ", ".join(e.constraint_violations),
                )
                for e in infeasible
            ]
        )
        result = selected.result
        binding: list[str] = []
        # Binding names are based on actual equality, not merely configured limits.
        for name, actual, limit in (
            (
                "minimum_required_illicit_recovery",
                result.modeled_tainted_capital_intercepted,
                constraints.minimum_required_illicit_recovery,
            ),
            (
                "maximum_legitimate_capital_affected",
                result.modeled_legitimate_capital_affected,
                constraints.maximum_legitimate_capital_affected,
            ),
            (
                "maximum_affected_accounts",
                result.number_of_affected_accounts,
                constraints.maximum_affected_accounts,
            ),
            (
                "maximum_affected_edges",
                result.number_of_affected_edges,
                constraints.maximum_affected_edges,
            ),
        ):
            if limit is not None and actual == limit:
                binding.append(name)
        if (
            constraints.minimum_provenance_confidence is not None
            and result.provenance_confidence
            == constraints.minimum_provenance_confidence
        ):
            binding.append("minimum_provenance_confidence")
        if constraints.maximum_interventions == 1:
            binding.append("maximum_interventions")
        return OptimizationExplanation(
            recommendation_reason=(
                "Recommended because it is feasible and Pareto-efficient; "
                "remaining Pareto ties use deterministic recovery, collateral, "
                "efficiency, scope, and intervention-ID ordering."
            ),
            illicit_capital_intercepted=result.modeled_tainted_capital_intercepted,
            legitimate_capital_affected=result.modeled_legitimate_capital_affected,
            recovery_efficiency=selected.recovery_efficiency,
            competing_candidates=tuple(sorted(comparisons, key=lambda c: c.intervention_id)),
            binding_constraints=tuple(binding),
            provenance_confidence=result.provenance_confidence,
        )
