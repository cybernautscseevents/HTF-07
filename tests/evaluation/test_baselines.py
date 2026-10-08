from datetime import datetime, timezone

from backend.app.counterfactual.models import (
    CounterfactualResult,
    InterventionCandidate,
    InterventionType,
)
from backend.app.evaluation.baselines import (
    highest_risk,
    highest_tainted_balance,
    highest_transaction_value,
    maximum_immediate_recovery,
)
from backend.app.optimization.models import InterventionEvaluation


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def evaluation(account: str, recovery: int = 1, feasible: bool = True):
    candidate = InterventionCandidate(InterventionType.ACCOUNT_HOLD, target_account_id=account)
    result = CounterfactualResult(
        intervention_id=account,
        intervention_type=InterventionType.ACCOUNT_HOLD,
        target_account_id=account,
        target_event_id=None,
        simulation_timestamp=NOW,
        modeled_tainted_capital_intercepted=recovery,
        modeled_legitimate_capital_affected=1,
        remaining_downstream_taint=0,
        number_of_affected_edges=1,
        number_of_affected_accounts=1,
        provenance_coverage=1.0,
        provenance_confidence=1.0,
        source_interception_details=(),
        explanation="test",
        blocked_event_ids=(),
        affected_account_ids=(),
    )
    return InterventionEvaluation(candidate, result, feasible, (), 1)


def test_baselines_select_expected_values_and_stable_tie_break():
    items = (evaluation("z", 10), evaluation("a", 10), evaluation("infeasible", 100, False))
    assert highest_risk(items, {"z": 0.9, "a": 0.9}, {}, {}) .intervention_id == "a"
    assert highest_tainted_balance(items, {}, {"z": 4, "a": 5}, {}).intervention_id == "a"
    assert highest_transaction_value(items, {}, {}, {"z": 8, "a": 9}).intervention_id == "a"
    assert maximum_immediate_recovery(items, {}, {}, {}).intervention_id == "a"


def test_baselines_return_none_without_feasible_candidates():
    assert highest_risk((evaluation("a", feasible=False),), {"a": 1}, {}, {}) is None
