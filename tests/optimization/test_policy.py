from __future__ import annotations

from backend.app.optimization.policy import check_constraints
from backend.app.optimization.models import OptimizationConstraints

from tests.optimization.test_optimizer import result


def test_policy_reports_each_hard_limit_deterministically() -> None:
    violations = check_constraints(
        result(
            "a",
            intercepted=10,
            legitimate=50,
            accounts=3,
            edges=4,
            confidence=0.5,
        ),
        OptimizationConstraints(
            minimum_required_illicit_recovery=11,
            maximum_legitimate_capital_affected=49,
            maximum_affected_accounts=2,
            maximum_affected_edges=3,
            minimum_provenance_confidence=0.9,
        ),
    )
    assert violations == (
        "minimum_required_illicit_recovery",
        "maximum_legitimate_capital_affected",
        "maximum_affected_accounts",
        "maximum_affected_edges",
        "minimum_provenance_confidence",
    )
