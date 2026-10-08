from __future__ import annotations

from datetime import datetime, timezone

from backend.app.counterfactual.models import (
    CounterfactualResult,
    InterventionCandidate,
    InterventionType,
)
from backend.app.optimization import (
    MultiObjectiveInterventionOptimizer,
    ObservedFutureCounterfactualEvaluator,
    OptimizationConstraints,
    recovery_efficiency,
)
from backend.app.counterfactual.simulator import CounterfactualSimulator
from backend.app.taint.engine import TaintEngine
from backend.app.taint.models import TaintSeed
from tests.counterfactual.conftest import T0, make_graph, simple_chain_events


SIMULATION_TIME = datetime(2026, 10, 9, 9, tzinfo=timezone.utc)


def candidate(account: str) -> InterventionCandidate:
    return InterventionCandidate(
        intervention_type=InterventionType.ACCOUNT_HOLD,
        target_account_id=account,
    )


def result(
    intervention_id: str,
    *,
    intercepted: int,
    legitimate: int,
    accounts: int = 1,
    edges: int = 1,
    confidence: float = 1.0,
) -> CounterfactualResult:
    return CounterfactualResult(
        intervention_id=intervention_id,
        intervention_type=InterventionType.ACCOUNT_HOLD,
        target_account_id=intervention_id,
        target_event_id=None,
        simulation_timestamp=SIMULATION_TIME,
        modeled_tainted_capital_intercepted=intercepted,
        modeled_legitimate_capital_affected=legitimate,
        remaining_downstream_taint=0,
        number_of_affected_edges=edges,
        number_of_affected_accounts=accounts,
        provenance_coverage=1.0,
        provenance_confidence=confidence,
        source_interception_details=(),
        explanation="synthetic evaluator result",
        blocked_event_ids=(),
        affected_account_ids=(),
    )


class MappingEvaluator:
    def __init__(self, values: dict[str, CounterfactualResult]) -> None:
        self.values = values
        self.calls: list[datetime] = []

    def evaluate(self, item: InterventionCandidate, timestamp: datetime) -> CounterfactualResult:
        self.calls.append(timestamp)
        assert item.target_account_id is not None
        return self.values[item.target_account_id]


def optimize(
    values: dict[str, CounterfactualResult],
    candidates: list[InterventionCandidate],
    constraints: OptimizationConstraints | None = None,
):
    return MultiObjectiveInterventionOptimizer(MappingEvaluator(values)).optimize(
        candidates, SIMULATION_TIME, constraints
    )


def test_empty_candidates_have_no_recommendation() -> None:
    output = optimize({}, [])
    assert output.evaluations == ()
    assert output.selected_evaluation is None
    assert output.pareto_frontier.size == 0


def test_pareto_frontier_and_dominated_candidate() -> None:
    output = optimize(
        {
            "a": result("a", intercepted=100, legitimate=20),
            "b": result("b", intercepted=90, legitimate=40),
            "c": result("c", intercepted=80, legitimate=10),
        },
        [candidate("a"), candidate("b"), candidate("c")],
    )
    assert {e.intervention_id for e in output.pareto_frontier.non_dominated} == {"a", "c"}
    assert [e.intervention_id for e in output.pareto_frontier.dominated] == ["b"]
    assert output.selected_candidate == candidate("a")


def test_hard_constraints_reject_candidates_and_report_no_feasible() -> None:
    output = optimize(
        {"a": result("a", intercepted=100, legitimate=20, confidence=0.8)},
        [candidate("a")],
        OptimizationConstraints(
            minimum_required_illicit_recovery=101,
            maximum_legitimate_capital_affected=10,
            minimum_provenance_confidence=0.9,
        ),
    )
    assert output.selected_evaluation is None
    assert output.infeasible_evaluations[0].constraint_violations == (
        "minimum_required_illicit_recovery",
        "maximum_legitimate_capital_affected",
        "minimum_provenance_confidence",
    )
    assert "No feasible intervention" in output.explanation.recommendation_reason


def test_exact_tie_breaking_and_efficiency() -> None:
    output = optimize(
        {
            "z": result("z", intercepted=100, legitimate=20, accounts=2, edges=2),
            "a": result("a", intercepted=100, legitimate=20, accounts=1, edges=2),
        },
        [candidate("z"), candidate("a")],
    )
    assert output.selected_candidate == candidate("a")
    assert recovery_efficiency(100, 20) == 5
    assert recovery_efficiency(0, 0) == 0


def test_deduplication_order_and_timestamp_preservation() -> None:
    evaluator = MappingEvaluator({"a": result("a", intercepted=10, legitimate=0)})
    item = candidate("a")
    output = MultiObjectiveInterventionOptimizer(evaluator).optimize(
        [item, item], SIMULATION_TIME
    )
    assert len(output.evaluations) == 1
    assert evaluator.calls == [SIMULATION_TIME]
    assert output.evaluations[0].result.simulation_timestamp == SIMULATION_TIME


def test_zero_collateral_integer_money_and_scope_constraints() -> None:
    output = optimize(
        {"a": result("a", intercepted=12345, legitimate=0, accounts=2, edges=3)},
        [candidate("a")],
        OptimizationConstraints(maximum_affected_accounts=2, maximum_affected_edges=3),
    )
    evaluation = output.selected_evaluation
    assert evaluation is not None
    assert evaluation.result.modeled_tainted_capital_intercepted == 12345
    assert evaluation.recovery_efficiency == 12345
    assert output.explanation.binding_constraints == (
        "maximum_affected_accounts",
        "maximum_affected_edges",
        "maximum_interventions",
    )


def test_observed_evaluator_preserves_authoritative_simulator() -> None:
    class Simulator:
        def simulate(self, item, timestamp):
            return result("a", intercepted=1, legitimate=2)

    item = candidate("a")
    evaluator = ObservedFutureCounterfactualEvaluator(Simulator())
    assert evaluator.evaluate(item, SIMULATION_TIME).modeled_tainted_capital_intercepted == 1


def test_real_simulator_evaluates_account_and_edge_candidates_without_mutation() -> None:
    graph = make_graph(*simple_chain_events())
    baseline = TaintEngine().run(
        graph,
        [TaintSeed(case_id="case", transaction_id="tx-e1", tainted_amount_minor_units=100_00)],
    )
    baseline_snapshot = baseline
    simulator = CounterfactualSimulator(graph, baseline)
    output = MultiObjectiveInterventionOptimizer(
        ObservedFutureCounterfactualEvaluator(simulator)
    ).optimize(
        [
            InterventionCandidate(
                intervention_type=InterventionType.ACCOUNT_HOLD,
                target_account_id="B",
            ),
            InterventionCandidate(
                intervention_type=InterventionType.EDGE_HOLD,
                target_event_id="e2",
            ),
        ],
        T0.replace(minute=5),
    )
    assert len(output.evaluations) == 2
    assert {e.result.intervention_type for e in output.evaluations} == {
        InterventionType.ACCOUNT_HOLD,
        InterventionType.EDGE_HOLD,
    }
    assert all(e.result.simulation_timestamp == T0.replace(minute=5) for e in output.evaluations)
    assert baseline is baseline_snapshot
    assert baseline.allocations == baseline_snapshot.allocations
