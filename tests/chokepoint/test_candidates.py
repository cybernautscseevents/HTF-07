"""Tests for chokepoint search orchestration, candidate generation, and optimizer integration."""

from __future__ import annotations

from datetime import timedelta
import pytest

from backend.app.chokepoint.candidates import (
    TemporalChokepointSearcher,
    evaluate_chokepoint_candidates_with_optimizer,
    find_temporal_chokepoint,
    generate_chokepoint_candidates,
)
from backend.app.chokepoint.models import (
    ChokepointSearchConfig,
    ChokepointStatus,
)
from backend.app.counterfactual.models import (
    InterventionCandidate,
    InterventionType,
)
from backend.app.counterfactual.simulator import CounterfactualSimulator
from backend.app.optimization.models import OptimizationConstraints
from backend.app.taint.engine import TaintEngine
from backend.app.taint.models import TaintSeed
from tests.counterfactual.conftest import T0, make_event, make_graph


def test_end_to_end_chokepoint_search_with_simulator() -> None:
    """Run full chokepoint search integrated with CounterfactualSimulator."""
    # Graph:
    # A -> B at t=0 (seed transaction, 100_00)
    # B -> C at t=10 (100_00)
    # C -> D at t=20 (100_00)
    e1 = make_event("e1", "A", "B", 100_00, 0)
    e2 = make_event("e2", "B", "C", 100_00, 10)
    e3 = make_event("e3", "C", "D", 100_00, 20)
    graph = make_graph(e1, e2, e3)

    taint_engine = TaintEngine()
    baseline = taint_engine.run(
        graph,
        [TaintSeed(case_id="case-1", transaction_id=e1.transaction_id, tainted_amount_minor_units=100_00)],
    )

    sim_time = T0 + timedelta(minutes=5)
    simulator = CounterfactualSimulator(graph, baseline)

    result = find_temporal_chokepoint(
        graph=graph,
        source_account_ids=["B"],
        sink_account_ids=["D"],
        simulation_timestamp=sim_time,
        simulator=simulator,
    )

    assert result.status == ChokepointStatus.OPTIMAL_CUT_FOUND
    assert result.is_feasible is True
    assert result.cut_size >= 1
    assert result.is_cut_verified is True
    assert len(result.candidates) == result.cut_size
    assert all(c.intervention_type == InterventionType.EDGE_HOLD for c in result.candidates)


def test_cut_verification_disconnects_all_paths() -> None:
    """Verifies that removing the returned cut guarantees 0 remaining temporal paths."""
    e1 = make_event("e1", "A", "B", 100_00, 0)
    e2 = make_event("e2", "A", "C", 100_00, 0)
    e3 = make_event("e3", "B", "D", 100_00, 10)
    e4 = make_event("e4", "C", "D", 100_00, 10)
    graph = make_graph(e1, e2, e3, e4)

    result = find_temporal_chokepoint(
        graph=graph,
        source_account_ids=["A"],
        sink_account_ids=["D"],
        simulation_timestamp=T0,
    )

    assert result.status == ChokepointStatus.OPTIMAL_CUT_FOUND
    assert result.is_cut_verified is True
    assert result.diagnostics.initial_path_count == 2
    assert result.diagnostics.residual_path_count == 0


def test_candidates_compatible_with_optimizer() -> None:
    """Intervention candidates generated from chokepoint cut evaluate cleanly in optimizer."""
    e1 = make_event("e1", "A", "B", 100_00, 0)
    e2 = make_event("e2", "B", "C", 100_00, 10)
    graph = make_graph(e1, e2)

    baseline = TaintEngine().run(
        graph,
        [TaintSeed(case_id="case-1", transaction_id=e1.transaction_id, tainted_amount_minor_units=100_00)],
    )
    simulator = CounterfactualSimulator(graph, baseline)
    sim_time = T0 + timedelta(minutes=5)

    search_result = find_temporal_chokepoint(
        graph=graph,
        source_account_ids=["B"],
        sink_account_ids=["C"],
        simulation_timestamp=sim_time,
        simulator=simulator,
    )

    opt_result = evaluate_chokepoint_candidates_with_optimizer(
        search_result=search_result,
        simulator=simulator,
        simulation_timestamp=sim_time,
        constraints=OptimizationConstraints(minimum_required_illicit_recovery=0),
    )

    assert len(opt_result.evaluations) == len(search_result.candidates)
    assert opt_result.selected_evaluation is not None
    assert opt_result.selected_candidate.target_event_id == "e2"


def test_taint_and_graph_immutability() -> None:
    """Search execution does not alter baseline taint result or graph."""
    e1 = make_event("e1", "A", "B", 100_00, 0)
    e2 = make_event("e2", "B", "C", 100_00, 10)
    graph = make_graph(e1, e2)

    baseline = TaintEngine().run(
        graph,
        [TaintSeed(case_id="case-1", transaction_id=e1.transaction_id, tainted_amount_minor_units=100_00)],
    )
    initial_allocations_len = len(baseline.allocations)
    initial_node_count = graph.node_count

    simulator = CounterfactualSimulator(graph, baseline)
    _ = find_temporal_chokepoint(
        graph=graph,
        source_account_ids=["A"],
        sink_account_ids=["C"],
        simulation_timestamp=T0,
        simulator=simulator,
    )

    assert len(baseline.allocations) == initial_allocations_len
    assert graph.node_count == initial_node_count


def test_generate_chokepoint_candidates_helper() -> None:
    """Helper returns deduplicated, individual InterventionCandidate instances."""
    e1 = make_event("e1", "A", "B", 100_00, 10)
    candidates = generate_chokepoint_candidates(
        events=[e1],
        source_account_ids=["A"],
        sink_account_ids=["B"],
        simulation_timestamp=T0,
    )

    assert len(candidates) == 1
    assert candidates[0].intervention_type == InterventionType.EDGE_HOLD
    assert candidates[0].target_event_id == "e1"


def test_invalid_input_handling() -> None:
    """Invalid inputs return ChokepointSearchResult with INVALID_INPUT status."""
    res = find_temporal_chokepoint(
        source_account_ids=[],
        sink_account_ids=["B"],
    )
    assert res.status == ChokepointStatus.INVALID_INPUT
    assert res.cut_size == 0
    assert not res.is_feasible


def test_budget_exceeded_handling() -> None:
    """Searcher gracefully catches budget exceeded and returns BUDGET_EXCEEDED status."""
    events = [make_event(f"e{i}", "A", "B", 10_00, i + 1) for i in range(20)]
    config = ChokepointSearchConfig(max_active_events=5)

    res = find_temporal_chokepoint(
        events=events,
        source_account_ids=["A"],
        sink_account_ids=["B"],
        config=config,
    )

    assert res.status == ChokepointStatus.BUDGET_EXCEEDED
    assert res.cut_size == 0
    assert "Active event count" in res.diagnostics.pruning_reasons[0]


def test_explanation_structure() -> None:
    """Explanation contains all required audit fields."""
    e1 = make_event("e1", "A", "B", 100_00, 10)
    res = find_temporal_chokepoint(
        events=[e1],
        source_account_ids=["A"],
        sink_account_ids=["B"],
        simulation_timestamp=T0,
    )

    expl = res.explanation
    assert expl.sources_analyzed == ("A",)
    assert expl.sinks_targeted == ("B",)
    assert expl.cut_edge_ids == ("e1",)
    assert "Dinic's algorithm evaluated" in expl.cost_minimality_rationale
    assert len(expl.limitations) >= 4
    assert expl.complete_cut_disconnects_all_paths is True
