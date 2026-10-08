"""Hard policy checks for counterfactual intervention evaluations."""

from __future__ import annotations

from backend.app.counterfactual.models import CounterfactualResult
from backend.app.optimization.models import OptimizationConstraints


def check_constraints(
    result: CounterfactualResult,
    constraints: OptimizationConstraints,
) -> tuple[str, ...]:
    """Return all violated policy constraints in stable declaration order."""
    violations: list[str] = []
    if (
        result.modeled_tainted_capital_intercepted
        < constraints.minimum_required_illicit_recovery
    ):
        violations.append(
            "minimum_required_illicit_recovery"
        )
    if (
        constraints.maximum_legitimate_capital_affected is not None
        and result.modeled_legitimate_capital_affected
        > constraints.maximum_legitimate_capital_affected
    ):
        violations.append("maximum_legitimate_capital_affected")
    if (
        constraints.maximum_affected_accounts is not None
        and result.number_of_affected_accounts > constraints.maximum_affected_accounts
    ):
        violations.append("maximum_affected_accounts")
    if (
        constraints.maximum_affected_edges is not None
        and result.number_of_affected_edges > constraints.maximum_affected_edges
    ):
        violations.append("maximum_affected_edges")
    if constraints.maximum_interventions < 1:
        violations.append("maximum_interventions")
    if (
        constraints.minimum_provenance_confidence is not None
        and result.provenance_confidence < constraints.minimum_provenance_confidence
    ):
        violations.append("minimum_provenance_confidence")
    return tuple(violations)
