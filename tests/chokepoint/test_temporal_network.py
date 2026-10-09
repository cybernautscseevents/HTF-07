"""Tests for sparse time-expanded causal network construction and validation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from backend.app.chokepoint.models import ChokepointSearchConfig
from backend.app.chokepoint.temporal_network import (
    BudgetExceededError,
    NormalizedEvent,
    build_time_expanded_network,
    extract_normalized_event,
)
from backend.app.forecast.models import ForecastTransactionEvent
from backend.app.graph.temporal_graph import TemporalGraph
from tests.counterfactual.conftest import T0, make_event, make_graph

UTC = timezone.utc


def test_strictly_increasing_timestamps() -> None:
    """Network properly chains events when timestamps are strictly increasing."""
    # A -> B at t=0, B -> C at t=10
    e1 = make_event("e1", "A", "B", 100_00, 0)
    e2 = make_event("e2", "B", "C", 100_00, 10)

    network = build_time_expanded_network(
        events=[e1, e2],
        source_account_ids=["A"],
        sink_account_ids=["C"],
    )

    assert network.num_nodes > 0
    assert "e1" in network.event_lookup
    assert "e2" in network.event_lookup
    assert network.total_finite_capacity > 0


def test_same_timestamp_path_not_temporally_valid() -> None:
    """Simultaneous transactions cannot be causally linked (MVP causality rule)."""
    # A -> B at t=10, B -> C at t=10 (identical timestamps)
    e1 = make_event("e1", "A", "B", 100_00, 10)
    e2 = make_event("e2", "B", "C", 100_00, 10)

    network = build_time_expanded_network(
        events=[e1, e2],
        source_account_ids=["A"],
        sink_account_ids=["C"],
    )

    # In Dinic's solver, flow from SOURCE to SINK must be 0 because B@>10 cannot feed e2 at t=10
    from backend.app.chokepoint.min_cut import DinicSolver
    solver = DinicSolver(network.num_nodes, network.source_node, network.sink_node)
    for arc in network.arcs:
        solver.add_edge(arc.from_node, arc.to_node, arc.capacity)

    max_flow = solver.compute_max_flow()
    assert max_flow == 0, "Same-timestamp path must not transmit flow"


def test_sparse_scaling_no_cartesian_product() -> None:
    """Network size must scale linearly with event count, not Cartesian product."""
    events = [
        make_event(f"e{i}", f"A{i}", f"A{i+1}", 50_00, i * 5)
        for i in range(50)
    ]
    network = build_time_expanded_network(
        events=events,
        source_account_ids=["A0"],
        sink_account_ids=["A50"],
    )

    # 50 events -> vertices <= 4 * 50 + 2 = 202, arcs <= 7 * 50 = 350
    assert network.num_nodes <= 4 * len(events) + 2
    assert len(network.arcs) <= 7 * len(events)


def test_historical_events_ineligible() -> None:
    """Events occurring at or before simulation_timestamp are historical and ineligible."""
    sim_time = T0 + timedelta(minutes=15)
    e_hist = make_event("e1", "A", "B", 100_00, 10)  # t=10 <= t_sim (15)
    e_fut = make_event("e2", "B", "C", 100_00, 20)   # t=20 > t_sim (15)

    network = build_time_expanded_network(
        events=[e_hist, e_fut],
        source_account_ids=["A"],
        sink_account_ids=["C"],
        simulation_timestamp=sim_time,
    )

    assert "e1" in network.ineligible_event_ids
    assert "e2" in network.eligible_event_ids
    assert network.total_finite_capacity == 1  # N=1, cost = 0 * (1 + 1) + 1 = 1


def test_future_ground_truth_leakage_prevention() -> None:
    """Events not explicitly marked eligible cannot be cut even if in the future."""
    e1 = make_event("e1", "A", "B", 100_00, 10)
    e2 = make_event("e2", "B", "C", 100_00, 20)

    # Caller only permits intervention on e1
    network = build_time_expanded_network(
        events=[e1, e2],
        source_account_ids=["A"],
        sink_account_ids=["C"],
        eligible_event_ids=["e1"],
    )

    assert network.eligible_event_ids == ("e1",)
    assert "e2" in network.ineligible_event_ids


def test_forecast_event_eligibility() -> None:
    """ForecastTransactionEvent is supported and marked is_forecast=True."""
    fc_event = ForecastTransactionEvent(
        event_id="fc-1",
        transaction_id="tx-fc-1",
        sender_account_id="MULE_1",
        receiver_account_id="CASH_OUT",
        amount_minor_units=500_00,
        currency="INR",
        occurred_at=T0 + timedelta(minutes=30),
        probability=0.85,
        path_id="path-1",
        hop_index=1,
    )

    network = build_time_expanded_network(
        events=[fc_event],
        source_account_ids=["MULE_1"],
        sink_account_ids=["CASH_OUT"],
    )

    norm = network.event_lookup["fc-1"]
    assert norm.is_forecast is True
    assert norm.amount_minor_units == 500_00
    assert norm.sender_account_id == "MULE_1"
    assert norm.receiver_account_id == "CASH_OUT"


def test_missing_or_invalid_source_sink_inputs() -> None:
    """Missing or overlapping source/sink accounts raise ValueError."""
    e = make_event("e1", "A", "B", 100_00, 0)

    with pytest.raises(ValueError, match="source_account_ids must be non-empty"):
        build_time_expanded_network([e], source_account_ids=[], sink_account_ids=["B"])

    with pytest.raises(ValueError, match="sink_account_ids must be non-empty"):
        build_time_expanded_network([e], source_account_ids=["A"], sink_account_ids=[])

    with pytest.raises(ValueError, match="cannot overlap"):
        build_time_expanded_network([e], source_account_ids=["A"], sink_account_ids=["A"])


def test_budget_exceeded_limits() -> None:
    """Exceeding configured budget limits raises BudgetExceededError."""
    events = [make_event(f"e{i}", "A", "B", 10_00, i) for i in range(10)]
    config = ChokepointSearchConfig(max_active_events=5)

    with pytest.raises(BudgetExceededError, match="Active event count"):
        build_time_expanded_network(
            events=events,
            source_account_ids=["A"],
            sink_account_ids=["B"],
            config=config,
        )


def test_exact_integer_capacity_arithmetic() -> None:
    """Verifies exact integer arithmetic for large minor-unit values."""
    large_collateral = 987_654_321_000_00  # large paise amount
    e = make_event("e1", "A", "B", 1_000_00, 10)

    network = build_time_expanded_network(
        events=[e],
        source_account_ids=["A"],
        sink_account_ids=["B"],
        collateral_lookup={"e1": large_collateral},
    )

    # N = 1, cost = collateral * (1 + 1) + 1 = collateral * 2 + 1
    expected_encoded = large_collateral * 2 + 1
    assert network.total_finite_capacity == expected_encoded
    assert network.inf_capacity == expected_encoded + 1
    assert isinstance(network.inf_capacity, int)


def test_graph_immutability() -> None:
    """Building the network must not mutate the underlying TemporalGraph."""
    graph = make_graph(
        make_event("e1", "A", "B", 100_00, 0),
        make_event("e2", "B", "C", 100_00, 10),
    )
    initial_node_count = graph.node_count
    initial_edge_count = graph.edge_count

    _ = build_time_expanded_network(
        events=graph.events_between(active_only=True),
        source_account_ids=["A"],
        sink_account_ids=["C"],
    )

    assert graph.node_count == initial_node_count
    assert graph.edge_count == initial_edge_count
