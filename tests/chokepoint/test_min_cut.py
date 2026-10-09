"""Tests for Dinic's minimum-cut algorithm and chokepoint extraction."""

from __future__ import annotations

from datetime import timedelta
import pytest

from backend.app.chokepoint.min_cut import DinicSolver, compute_temporal_min_cut
from backend.app.chokepoint.models import ChokepointStatus
from backend.app.chokepoint.temporal_network import build_time_expanded_network
from tests.counterfactual.conftest import T0, make_event


def test_single_chain_one_cut_edge() -> None:
    """A -> B -> C: a single cut edge isolates source A from sink C."""
    # A -> B at t=0, B -> C at t=10
    e1 = make_event("e1", "A", "B", 100_00, 0)
    e2 = make_event("e2", "B", "C", 100_00, 10)

    # e1 has collateral 50_00, e2 has collateral 10_00
    network = build_time_expanded_network(
        events=[e1, e2],
        source_account_ids=["A"],
        sink_account_ids=["C"],
        collateral_lookup={"e1": 50_00, "e2": 10_00},
    )

    status, cut_edges, total_cost, total_collateral = compute_temporal_min_cut(network)

    assert status == ChokepointStatus.OPTIMAL_CUT_FOUND
    assert len(cut_edges) == 1
    # Minimum collateral is e2 (10_00 < 50_00)
    assert cut_edges[0].event_id == "e2"
    assert cut_edges[0].estimated_legitimate_collateral_minor_units == 10_00


def test_diamond_topology_multiple_cut_edges() -> None:
    """Diamond topology: A -> B -> D and A -> C -> D."""
    # A -> B at t=0, A -> C at t=0
    # B -> D at t=10, C -> D at t=10
    e_ab = make_event("e_ab", "A", "B", 100_00, 0)
    e_ac = make_event("e_ac", "A", "C", 100_00, 0)
    e_bd = make_event("e_bd", "B", "D", 100_00, 10)
    e_cd = make_event("e_cd", "C", "D", 100_00, 10)

    # High collateral on A's branches (500_00 each), low collateral on D's branches (20_00 each)
    network = build_time_expanded_network(
        events=[e_ab, e_ac, e_bd, e_cd],
        source_account_ids=["A"],
        sink_account_ids=["D"],
        collateral_lookup={"e_ab": 500_00, "e_ac": 500_00, "e_bd": 20_00, "e_cd": 20_00},
    )

    status, cut_edges, total_cost, total_collateral = compute_temporal_min_cut(network)

    assert status == ChokepointStatus.OPTIMAL_CUT_FOUND
    assert len(cut_edges) == 2
    cut_ids = {edge.event_id for edge in cut_edges}
    assert cut_ids == {"e_bd", "e_cd"}
    assert total_collateral == 40_00


def test_diamond_topology_prefers_single_zero_collateral_edge_over_multiple_zero_collateral_splits() -> None:
    """When all cuts have zero legitimate collateral, secondary objective strictly prefers the single cut edge.

    Topology:
      S -> M1 at t=0
      S -> M2 at t=0
      M1 -> HUB at t=10
      M2 -> HUB at t=10
      HUB -> SINK at t=20 (single exit edge)

    Candidate cuts:
      - Split cut: {S->M1, S->M2} (size 2, collateral 0, encoded cost 2)
      - Reconvergence cut: {M1->HUB, M2->HUB} (size 2, collateral 0, encoded cost 2)
      - Exit cut: {HUB->SINK} (size 1, collateral 0, encoded cost 1)

    Since all edges have 0 collateral, the exact optimum must prefer HUB->SINK.
    """
    e_split1 = make_event("e_split1", "S", "M1", 100_00, 0)
    e_split2 = make_event("e_split2", "S", "M2", 100_00, 0)
    e_reconv1 = make_event("e_reconv1", "M1", "HUB", 100_00, 10)
    e_reconv2 = make_event("e_reconv2", "M2", "HUB", 100_00, 10)
    e_exit = make_event("e_exit", "HUB", "SINK", 200_00, 20)

    network = build_time_expanded_network(
        events=[e_split1, e_split2, e_reconv1, e_reconv2, e_exit],
        source_account_ids=["S"],
        sink_account_ids=["SINK"],
        collateral_lookup={
            "e_split1": 0,
            "e_split2": 0,
            "e_reconv1": 0,
            "e_reconv2": 0,
            "e_exit": 0,
        },
    )

    status, cut_edges, total_cost, total_collateral = compute_temporal_min_cut(network)

    assert status == ChokepointStatus.OPTIMAL_CUT_FOUND
    assert len(cut_edges) == 1
    assert cut_edges[0].event_id == "e_exit"
    assert total_cost == 1
    assert total_collateral == 0


def test_shared_chokepoint_bridge_topology() -> None:
    """Fan-out to mule hub, which funnels through a single bridge edge to sink."""
    # A -> M1, A -> M2
    # M1 -> Bridge, M2 -> Bridge
    # Bridge -> Sink
    e1 = make_event("e1", "A", "M1", 100_00, 0)
    e2 = make_event("e2", "A", "M2", 100_00, 0)
    e3 = make_event("e3", "M1", "HUB", 100_00, 10)
    e4 = make_event("e4", "M2", "HUB", 100_00, 10)
    e_bridge = make_event("e_bridge", "HUB", "SINK", 200_00, 20)

    network = build_time_expanded_network(
        events=[e1, e2, e3, e4, e_bridge],
        source_account_ids=["A"],
        sink_account_ids=["SINK"],
        collateral_lookup={"e_bridge": 10_00, "e1": 100_00, "e2": 100_00, "e3": 100_00, "e4": 100_00},
    )

    status, cut_edges, total_cost, total_collateral = compute_temporal_min_cut(network)

    assert status == ChokepointStatus.OPTIMAL_CUT_FOUND
    assert len(cut_edges) == 1
    assert cut_edges[0].event_id == "e_bridge"


def test_multiple_sources() -> None:
    """Two independent fraud sources S1 and S2 funnelling towards SINK."""
    e1 = make_event("e1", "S1", "SINK", 50_00, 10)
    e2 = make_event("e2", "S2", "SINK", 50_00, 10)

    network = build_time_expanded_network(
        events=[e1, e2],
        source_account_ids=["S1", "S2"],
        sink_account_ids=["SINK"],
    )

    status, cut_edges, total_cost, total_collateral = compute_temporal_min_cut(network)

    assert status == ChokepointStatus.OPTIMAL_CUT_FOUND
    assert len(cut_edges) == 2
    cut_ids = {edge.event_id for edge in cut_edges}
    assert cut_ids == {"e1", "e2"}


def test_multiple_exit_sinks() -> None:
    """Single fraud source branching to two distinct cash-out destinations."""
    e1 = make_event("e1", "SRC", "EXIT1", 50_00, 10)
    e2 = make_event("e2", "SRC", "EXIT2", 50_00, 10)

    network = build_time_expanded_network(
        events=[e1, e2],
        source_account_ids=["SRC"],
        sink_account_ids=["EXIT1", "EXIT2"],
    )

    status, cut_edges, total_cost, total_collateral = compute_temporal_min_cut(network)

    assert status == ChokepointStatus.OPTIMAL_CUT_FOUND
    assert len(cut_edges) == 2
    cut_ids = {edge.event_id for edge in cut_edges}
    assert cut_ids == {"e1", "e2"}


def test_no_source_to_sink_path() -> None:
    """When source and sink are completely disconnected."""
    e1 = make_event("e1", "A", "B", 100_00, 10)
    e2 = make_event("e2", "C", "D", 100_00, 20)

    network = build_time_expanded_network(
        events=[e1, e2],
        source_account_ids=["A"],
        sink_account_ids=["D"],
    )

    status, cut_edges, total_cost, total_collateral = compute_temporal_min_cut(network)

    assert status == ChokepointStatus.NO_PATH_EXISTS
    assert len(cut_edges) == 0
    assert total_cost == 0


def test_minimum_cost_choice_different_collateral() -> None:
    """Between two candidate cuts of equal size, the one with lower collateral is chosen."""
    # S -> A -> SINK
    # Cut options: e1 (S->A) or e2 (A->SINK)
    e1 = make_event("e1", "S", "A", 100_00, 0)
    e2 = make_event("e2", "A", "SINK", 100_00, 10)

    network = build_time_expanded_network(
        events=[e1, e2],
        source_account_ids=["S"],
        sink_account_ids=["SINK"],
        collateral_lookup={"e1": 150_00, "e2": 30_00},
    )

    status, cut_edges, total_cost, total_collateral = compute_temporal_min_cut(network)

    assert status == ChokepointStatus.OPTIMAL_CUT_FOUND
    assert len(cut_edges) == 1
    assert cut_edges[0].event_id == "e2"
    assert total_collateral == 30_00


def test_deterministic_tie_breaking_equal_cost() -> None:
    """Equal cost cuts break ties deterministically across repeated runs."""
    e1 = make_event("e1", "S", "A", 100_00, 0)
    e2 = make_event("e2", "A", "SINK", 100_00, 10)

    # Identical collateral on both
    network1 = build_time_expanded_network(
        events=[e1, e2],
        source_account_ids=["S"],
        sink_account_ids=["SINK"],
        collateral_lookup={"e1": 50_00, "e2": 50_00},
    )
    status1, cut1, cost1, col1 = compute_temporal_min_cut(network1)

    network2 = build_time_expanded_network(
        events=[e1, e2],
        source_account_ids=["S"],
        sink_account_ids=["SINK"],
        collateral_lookup={"e1": 50_00, "e2": 50_00},
    )
    status2, cut2, cost2, col2 = compute_temporal_min_cut(network2)

    assert status1 == status2
    assert cost1 == cost2
    assert [e.event_id for e in cut1] == [e.event_id for e in cut2]


def test_zero_collateral_cut_edges() -> None:
    """Zero collateral cut edges encode to cost 1 and are chosen."""
    e1 = make_event("e1", "S", "A", 100_00, 0)
    e2 = make_event("e2", "A", "SINK", 100_00, 10)

    network = build_time_expanded_network(
        events=[e1, e2],
        source_account_ids=["S"],
        sink_account_ids=["SINK"],
        collateral_lookup={"e1": 100_00, "e2": 0},
    )

    status, cut_edges, total_cost, total_collateral = compute_temporal_min_cut(network)

    assert status == ChokepointStatus.OPTIMAL_CUT_FOUND
    assert len(cut_edges) == 1
    assert cut_edges[0].event_id == "e2"
    assert cut_edges[0].estimated_legitimate_collateral_minor_units == 0
    # N=2, cost = 0 * 3 + 1 = 1
    assert total_cost == 1


def test_no_feasible_cut_when_path_is_ineligible() -> None:
    """If all paths require cutting historical/ineligible edges, return NO_FEASIBLE_CUT."""
    # S -> SINK at t=0, decision time is t=10 (hence S->SINK is historical/ineligible)
    sim_time = T0 + timedelta(minutes=10)
    e_hist = make_event("e1", "S", "SINK", 100_00, 0)

    network = build_time_expanded_network(
        events=[e_hist],
        source_account_ids=["S"],
        sink_account_ids=["SINK"],
        simulation_timestamp=sim_time,
    )

    status, cut_edges, total_cost, total_collateral = compute_temporal_min_cut(network)

    assert status == ChokepointStatus.NO_FEASIBLE_CUT
    assert len(cut_edges) == 0


def test_repeat_run_determinism() -> None:
    """Running 10 times consecutively produces identical results every time."""
    events = [
        make_event("e1", "SRC", "M1", 100_00, 0),
        make_event("e2", "SRC", "M2", 100_00, 0),
        make_event("e3", "M1", "DST", 100_00, 10),
        make_event("e4", "M2", "DST", 100_00, 10),
    ]

    first_result = None
    for _ in range(10):
        net = build_time_expanded_network(
            events=events,
            source_account_ids=["SRC"],
            sink_account_ids=["DST"],
            collateral_lookup={"e1": 10_00, "e2": 20_00, "e3": 5_00, "e4": 15_00},
        )
        status, cut, cost, col = compute_temporal_min_cut(net)
        res_tuple = (status, tuple(e.event_id for e in cut), cost, col)
        if first_result is None:
            first_result = res_tuple
        else:
            assert res_tuple == first_result
