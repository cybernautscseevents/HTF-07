"""Deterministic robust intervention selection policy.

Philosophical Distinction:
-------------------------
- Observed-world selection:
  "What is best given observed future transactions?"
- Forecast-aware selection:
  "What is best across plausible future trajectories?"

The robust selection policy implements the 5 primary considerations:
1. Feasibility probability / hard policy constraint compliance
2. Probability-weighted illicit recovery (expected interception)
3. Worst-case legitimate collateral (minimizing maximum collateral)
4. Worst-case recovery (maximizing guaranteed minimum recovery across futures)
5. Deterministic tie-breaking (scope metrics and stable candidate ordering)
"""

from __future__ import annotations

from typing import Sequence

from backend.app.forecast.models import ForecastAwareCounterfactualResult
from backend.app.optimization.models import (
    InterventionEvaluation,
    OptimizationConstraints,
    candidate_sort_key,
)


def robust_selection_sort_key(
    evaluation: InterventionEvaluation,
) -> tuple:
    """Return the deterministic robust sorting key for an evaluated intervention.

    Lower tuple values indicate superior candidates.
    """
    res = evaluation.result
    is_forecast_aware = isinstance(res, ForecastAwareCounterfactualResult)

    # 1. Feasibility compliance (feasible first -> 0, infeasible -> 1)
    feasibility_rank = 0 if evaluation.feasible else 1

    # 2. Probability-weighted illicit recovery (higher is better -> negate)
    expected_recovery = (
        res.expected_illicit_interception
        if is_forecast_aware
        else res.modeled_tainted_capital_intercepted
    )

    # 3. Worst-case legitimate collateral (lower is better -> positive)
    worst_collateral = (
        res.worst_case_legitimate_impact
        if is_forecast_aware
        else res.modeled_legitimate_capital_affected
    )

    # 4. Worst-case recovery (higher minimum recovery is better -> negate)
    worst_recovery = (
        res.worst_case_illicit_interception
        if is_forecast_aware
        else res.modeled_tainted_capital_intercepted
    )

    # 5. Scope & tie-breaking
    affected_accounts = res.number_of_affected_accounts
    affected_edges = res.number_of_affected_edges
    cand_key = candidate_sort_key(evaluation.candidate)

    return (
        feasibility_rank,
        -expected_recovery,
        worst_collateral,
        -worst_recovery,
        affected_accounts,
        affected_edges,
        cand_key,
    )


def select_robust_intervention(
    evaluations: Sequence[InterventionEvaluation],
    constraints: OptimizationConstraints | None = None,
) -> InterventionEvaluation | None:
    """Deterministically select the most robust intervention across futures.

    Parameters
    ----------
    evaluations : Sequence[InterventionEvaluation]
        Evaluated candidates.
    constraints : OptimizationConstraints, optional
        Policy limits.

    Returns
    -------
    InterventionEvaluation | None
        Selected candidate, or None if no feasible candidates exist.
    """
    if not evaluations:
        return None

    feasible = [e for e in evaluations if e.feasible]
    if not feasible:
        return None

    return min(feasible, key=robust_selection_sort_key)
