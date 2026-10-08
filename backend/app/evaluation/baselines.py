"""Deterministic baseline selectors for fair intervention comparisons."""

from __future__ import annotations

from typing import Callable, Iterable

from backend.app.counterfactual.models import InterventionCandidate, InterventionType
from backend.app.optimization.models import InterventionEvaluation

Evaluation = InterventionEvaluation
Selector = Callable[
    [tuple[Evaluation, ...], dict[str, float], dict[str, int], dict[str, int]],
    Evaluation | None,
]


def _key_id(evaluation: Evaluation) -> str:
    return evaluation.intervention_id


def _feasible_account_holds(evaluations: Iterable[Evaluation]) -> list[Evaluation]:
    return sorted(
        (
            item
            for item in evaluations
            if item.feasible
            and item.candidate.intervention_type == InterventionType.ACCOUNT_HOLD
        ),
        key=_key_id,
    )


def highest_risk(
    evaluations: tuple[Evaluation, ...],
    risk_scores: dict[str, float],
    tainted_balances: dict[str, int],
    transaction_values: dict[str, int],
) -> Evaluation | None:
    """Select the feasible account hold with highest observable risk score."""
    candidates = _feasible_account_holds(evaluations)
    return min(
        candidates,
        key=lambda e: (-risk_scores.get(e.candidate.target_account_id or "", 0.0), _key_id(e)),
        default=None,
    )


def highest_tainted_balance(
    evaluations: tuple[Evaluation, ...],
    risk_scores: dict[str, float],
    tainted_balances: dict[str, int],
    transaction_values: dict[str, int],
) -> Evaluation | None:
    """Select the feasible account hold with highest current tainted balance."""
    candidates = _feasible_account_holds(evaluations)
    return min(
        candidates,
        key=lambda e: (
            -tainted_balances.get(e.candidate.target_account_id or "", 0),
            _key_id(e),
        ),
        default=None,
    )


def highest_transaction_value(
    evaluations: tuple[Evaluation, ...],
    risk_scores: dict[str, float],
    tainted_balances: dict[str, int],
    transaction_values: dict[str, int],
) -> Evaluation | None:
    """Select the feasible account hold with highest relevant future value."""
    candidates = _feasible_account_holds(evaluations)
    return min(
        candidates,
        key=lambda e: (
            -transaction_values.get(e.candidate.target_account_id or "", 0),
            _key_id(e),
        ),
        default=None,
    )


def maximum_immediate_recovery(
    evaluations: tuple[Evaluation, ...],
    risk_scores: dict[str, float],
    tainted_balances: dict[str, int],
    transaction_values: dict[str, int],
) -> Evaluation | None:
    """Select maximum intercepted capital, without Pareto ranking."""
    candidates = sorted((e for e in evaluations if e.feasible), key=_key_id)
    return min(
        candidates,
        key=lambda e: (
            -e.result.modeled_tainted_capital_intercepted,
            e.result.modeled_legitimate_capital_affected,
            _key_id(e),
        ),
        default=None,
    )


BASELINE_SELECTORS: dict[str, Selector] = {
    "highest_risk": highest_risk,
    "highest_tainted_balance": highest_tainted_balance,
    "highest_transaction_value": highest_transaction_value,
    "maximum_immediate_recovery": maximum_immediate_recovery,
}
