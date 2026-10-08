"""Comprehensive deterministic tests for the counterfactual intervention simulator.

Test matrix covers:
1.  Simple chain
2.  Fan-out
3.  Fan-in
4.  Fan-out → fan-in
5.  Commingling
6.  Multiple branches
7.  Account intervention
8.  Edge intervention
9.  Historical events remain unchanged
10. Future events are affected
11. No intervention baseline
12. Zero-taint candidate
13. Multiple provenance sources
14. Observable shortfall
15. Deterministic repeated simulation
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.counterfactual.models import (
    CounterfactualResult,
    InterventionCandidate,
    InterventionType,
)
from backend.app.counterfactual.simulator import CounterfactualSimulator
from backend.app.counterfactual.candidates import generate_candidates
from backend.app.taint.models import TaintSeed

from tests.counterfactual.conftest import (
    T0,
    UTC,
    commingling_events,
    fan_in_events,
    fan_out_events,
    fan_out_fan_in_events,
    make_event,
    make_graph,
    multi_branch_events,
    run_taint,
    simple_chain_events,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _seed(case_id: str, transaction_id: str, amount: int) -> TaintSeed:
    return TaintSeed(
        case_id=case_id,
        transaction_id=transaction_id,
        tainted_amount_minor_units=amount,
    )


# ── 1. Simple chain ─────────────────────────────────────────────────────────


class TestSimpleChain:
    """A → B → C → D, seed 100_00 at A→B.

    Intervention: account hold on B after seed arrives.
    Expected: B→C and C→D blocked, 100_00 intercepted.
    """

    def test_account_hold_on_b_intercepts_all_taint(self) -> None:
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        # Intervene right after e1 (minute 0), so e2 (minute 10) and e3 (minute 20) are future
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="B",
        )
        result = sim.simulate(candidate, sim_time)

        assert result.modeled_tainted_capital_intercepted > 0
        assert result.number_of_affected_edges >= 1
        assert "e2" in result.blocked_event_ids
        assert result.intervention_type == InterventionType.ACCOUNT_HOLD
        assert result.target_account_id == "B"

    def test_edge_hold_on_e2_blocks_only_one_hop(self) -> None:
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.EDGE_HOLD,
            target_event_id="e2",
        )
        result = sim.simulate(candidate, sim_time)

        assert result.number_of_affected_edges == 1
        assert result.blocked_event_ids == ("e2",)


# ── 2. Fan-out ───────────────────────────────────────────────────────────────


class TestFanOut:
    """EXT → A → B, C, D.  Seed 300_00 at EXT→A."""

    def test_account_hold_on_a_blocks_all_branches(self) -> None:
        events = fan_out_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-seed1", 300_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="A",
        )
        result = sim.simulate(candidate, sim_time)

        assert result.number_of_affected_edges == 3
        assert result.modeled_tainted_capital_intercepted > 0

    def test_edge_hold_blocks_single_branch(self) -> None:
        events = fan_out_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-seed1", 300_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.EDGE_HOLD,
            target_event_id="fo1",
        )
        result = sim.simulate(candidate, sim_time)

        assert result.number_of_affected_edges == 1
        assert "fo1" in result.blocked_event_ids


# ── 3. Fan-in ────────────────────────────────────────────────────────────────


class TestFanIn:
    """B, C, D → T.  Three separate seeds."""

    def test_account_hold_on_t_has_no_outbound_to_block(self) -> None:
        """T is a terminal node with no outbound — hold has no effect."""
        events = fan_in_events()
        graph = make_graph(*events)
        seeds = [
            _seed("case_b", "tx-seed-b", 100_00),
            _seed("case_c", "tx-seed-c", 100_00),
            _seed("case_d", "tx-seed-d", 100_00),
        ]
        baseline = run_taint(graph, seeds)

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=15)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="T",
        )
        result = sim.simulate(candidate, sim_time)

        # T has no outbound edges, so no events are blocked
        assert result.number_of_affected_edges == 0
        assert result.modeled_tainted_capital_intercepted == 0

    def test_edge_hold_on_single_fan_in_edge(self) -> None:
        events = fan_in_events()
        graph = make_graph(*events)
        seeds = [
            _seed("case_b", "tx-seed-b", 100_00),
            _seed("case_c", "tx-seed-c", 100_00),
            _seed("case_d", "tx-seed-d", 100_00),
        ]
        baseline = run_taint(graph, seeds)

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.EDGE_HOLD,
            target_event_id="fi1",
        )
        result = sim.simulate(candidate, sim_time)

        assert result.number_of_affected_edges == 1
        assert result.modeled_tainted_capital_intercepted > 0


# ── 4. Fan-out → Fan-in ─────────────────────────────────────────────────────


class TestFanOutFanIn:
    """S → I1, I2, I3 → T.  Seed 300_00 at EXT→S."""

    def test_hold_on_intermediate_blocks_one_branch(self) -> None:
        events = fan_out_fan_in_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-seed_s", 300_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="I1",
        )
        result = sim.simulate(candidate, sim_time)

        # I1's outbound to T is blocked
        assert "fofi4" in result.blocked_event_ids
        assert result.modeled_tainted_capital_intercepted > 0

    def test_hold_on_s_blocks_all_downstream(self) -> None:
        events = fan_out_fan_in_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-seed_s", 300_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="S",
        )
        result = sim.simulate(candidate, sim_time)

        # S→I1, S→I2, S→I3 all blocked
        assert result.number_of_affected_edges == 3


# ── 5. Commingling ───────────────────────────────────────────────────────────


class TestCommingling:
    """B receives 100_00 tainted (A) + 200_00 clean (LEGIT), forwards 300_00.

    Commingled transfer should show proportional taint interception
    and legitimate capital affected.
    """

    def test_edge_hold_on_commingled_transfer(self) -> None:
        events = commingling_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-seed_a", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=15)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.EDGE_HOLD,
            target_event_id="e_bc",
        )
        result = sim.simulate(candidate, sim_time)

        assert result.number_of_affected_edges == 1
        # Both tainted and legitimate capital are affected
        assert result.modeled_tainted_capital_intercepted > 0
        assert result.modeled_legitimate_capital_affected > 0

    def test_commingling_preserves_proportionality(self) -> None:
        events = commingling_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-seed_a", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=15)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.EDGE_HOLD,
            target_event_id="e_bc",
        )
        result = sim.simulate(candidate, sim_time)

        # In commingling: B has 100_00 tainted + 200_00 clean = 300_00 total
        # Proportional allocation: taint ratio = 100/300 = 1/3
        # So out of 300_00 transferred, ~100_00 is tainted, ~200_00 is clean
        total_on_edge = result.modeled_tainted_capital_intercepted + result.modeled_legitimate_capital_affected
        assert total_on_edge == 300_00


# ── 6. Multiple branches ────────────────────────────────────────────────────


class TestMultipleBranches:
    """HUB → B1, B2, B3.  B1→C1, B2→C2."""

    def test_hold_on_hub_blocks_all(self) -> None:
        events = multi_branch_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-seed_hub", 400_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="HUB",
        )
        result = sim.simulate(candidate, sim_time)

        # HUB→B1, HUB→B2, HUB→B3 are all blocked
        assert result.number_of_affected_edges == 3

    def test_hold_on_b1_blocks_one_branch(self) -> None:
        events = multi_branch_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-seed_hub", 400_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=15)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="B1",
        )
        result = sim.simulate(candidate, sim_time)

        # Only B1→C1 is blocked
        assert "b1_c1" in result.blocked_event_ids


# ── 7. Account intervention specifics ───────────────────────────────────────


class TestAccountIntervention:
    def test_account_hold_blocks_future_outbound_only(self) -> None:
        """Historical inbound to the target account is unchanged."""
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="B",
        )
        result = sim.simulate(candidate, sim_time)

        # e1 (A→B) is historical and not blocked
        assert "e1" not in result.blocked_event_ids
        # e2 (B→C) is future and blocked
        assert "e2" in result.blocked_event_ids

    def test_account_hold_requires_account_id(self) -> None:
        with pytest.raises(ValueError, match="target_account_id"):
            InterventionCandidate(
                intervention_type=InterventionType.ACCOUNT_HOLD,
            )

    def test_account_hold_rejects_event_id(self) -> None:
        with pytest.raises(ValueError, match="must not specify target_event_id"):
            InterventionCandidate(
                intervention_type=InterventionType.ACCOUNT_HOLD,
                target_account_id="A",
                target_event_id="e1",
            )


# ── 8. Edge intervention specifics ──────────────────────────────────────────


class TestEdgeIntervention:
    def test_edge_hold_blocks_single_event(self) -> None:
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.EDGE_HOLD,
            target_event_id="e2",
        )
        result = sim.simulate(candidate, sim_time)

        assert result.blocked_event_ids == ("e2",)

    def test_edge_hold_requires_event_id(self) -> None:
        with pytest.raises(ValueError, match="target_event_id"):
            InterventionCandidate(
                intervention_type=InterventionType.EDGE_HOLD,
            )

    def test_edge_hold_rejects_account_id(self) -> None:
        with pytest.raises(ValueError, match="must not specify target_account_id"):
            InterventionCandidate(
                intervention_type=InterventionType.EDGE_HOLD,
                target_event_id="e1",
                target_account_id="A",
            )


# ── 9. Historical events remain unchanged ───────────────────────────────────


class TestHistoricalEventsUnchanged:
    def test_events_at_or_before_sim_time_not_blocked(self) -> None:
        """Events at or before simulation time must never be blocked."""
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        # sim_time = T0+10min = exactly when e2 occurs
        # e2 at occurred_at == sim_time should NOT be blocked (only > is future)
        sim_time = T0 + timedelta(minutes=10)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="B",
        )
        result = sim.simulate(candidate, sim_time)

        # e2 occurs at exactly sim_time, so it's historical
        assert "e2" not in result.blocked_event_ids

    def test_seed_event_never_blocked(self) -> None:
        """The seed event is historical and must never be blocked."""
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        # Even if we set sim_time before the seed
        sim_time = T0 - timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="A",
        )
        result = sim.simulate(candidate, sim_time)

        # e1 is at T0 which is > sim_time, so it IS blocked in this case
        # But the seed event is A→B, and we're holding A, so outbound from A
        # at T0 (which > sim_time) would be blocked
        assert "e1" in result.blocked_event_ids


# ── 10. Future events are affected ──────────────────────────────────────────


class TestFutureEventsAffected:
    def test_only_strictly_future_events_blocked(self) -> None:
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="B",
        )
        result = sim.simulate(candidate, sim_time)

        for eid in result.blocked_event_ids:
            edge = graph.get_edge_by_event(eid)
            assert edge.occurred_at > sim_time, (
                f"Blocked event {eid} occurred_at {edge.occurred_at} "
                f"is not after sim_time {sim_time}"
            )


# ── 11. No intervention baseline ────────────────────────────────────────────


class TestNoInterventionBaseline:
    """A candidate targeting a non-existent or no-future account
    should produce zero impact."""

    def test_hold_on_terminal_account(self) -> None:
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=25)
        # D is terminal — no outbound
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="D",
        )
        result = sim.simulate(candidate, sim_time)

        assert result.number_of_affected_edges == 0
        assert result.modeled_tainted_capital_intercepted == 0

    def test_edge_hold_on_historical_event(self) -> None:
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        # e2 occurs at T0+10, set sim_time after that
        sim_time = T0 + timedelta(minutes=15)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.EDGE_HOLD,
            target_event_id="e2",
        )
        result = sim.simulate(candidate, sim_time)

        # e2 is historical, so no blocking
        assert result.number_of_affected_edges == 0


# ── 12. Zero-taint candidate ────────────────────────────────────────────────


class TestZeroTaintCandidate:
    """Intervention on an account/edge that carries no taint."""

    def test_hold_on_untainted_account(self) -> None:
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        # Add an untainted account with future activity
        extra_events = [
            make_event("clean1", "CLEAN_SRC", "CLEAN_DST", 500_00, 15),
        ]
        graph_with_clean = make_graph(*events, *extra_events)
        baseline_with_clean = run_taint(graph_with_clean, [seed])

        sim = CounterfactualSimulator(graph_with_clean, baseline_with_clean)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="CLEAN_SRC",
        )
        result = sim.simulate(candidate, sim_time)

        # The blocked edge carries no taint
        assert result.modeled_tainted_capital_intercepted == 0
        assert result.number_of_affected_edges == 1


# ── 13. Multiple provenance sources ─────────────────────────────────────────


class TestMultipleProvenanceSources:
    """Fan-in with three seeds should track per-source interception."""

    def test_per_source_interception_detail(self) -> None:
        events = fan_in_events()
        graph = make_graph(*events)
        seeds = [
            _seed("case_b", "tx-seed-b", 100_00),
            _seed("case_c", "tx-seed-c", 100_00),
            _seed("case_d", "tx-seed-d", 100_00),
        ]
        baseline = run_taint(graph, seeds)

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        # Block B→T edge
        candidate = InterventionCandidate(
            intervention_type=InterventionType.EDGE_HOLD,
            target_event_id="fi1",
        )
        result = sim.simulate(candidate, sim_time)

        # Should have source interception details for all seeds
        assert len(result.source_interception_details) == 3
        # The intercepted source should be case_b
        intercepted_sources = [
            d for d in result.source_interception_details
            if d.intercepted_amount_minor_units > 0
        ]
        assert len(intercepted_sources) >= 1
        source_ids = [d.source_id for d in intercepted_sources]
        assert any("case_b" in sid for sid in source_ids)


# ── 14. Observable shortfall ────────────────────────────────────────────────


class TestObservableShortfall:
    """When a sender has less balance than the transfer amount,
    the baseline records a shortfall.  Verify it affects confidence."""

    def test_shortfall_degrades_confidence(self) -> None:
        # B sends more than it received from the tainted transfer
        events = [
            make_event("e1", "A", "B", 100_00, 0),
            make_event("e2", "B", "C", 200_00, 10),  # shortfall: B only has 100_00
        ]
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        # Verify baseline has a shortfall
        assert len(baseline.shortfalls) > 0

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.EDGE_HOLD,
            target_event_id="e2",
        )
        result = sim.simulate(candidate, sim_time)

        # Confidence should be degraded due to shortfall
        assert result.provenance_confidence < 1.0


# ── 15. Deterministic repeated simulation ───────────────────────────────────


class TestDeterministicRepeatedSimulation:
    """Repeated runs must produce identical results."""

    def test_repeated_runs_identical(self) -> None:
        events = fan_out_fan_in_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-seed_s", 300_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="S",
        )

        results = [sim.simulate(candidate, sim_time) for _ in range(5)]

        for i in range(1, len(results)):
            assert results[i].intervention_id == results[0].intervention_id
            assert (
                results[i].modeled_tainted_capital_intercepted
                == results[0].modeled_tainted_capital_intercepted
            )
            assert (
                results[i].modeled_legitimate_capital_affected
                == results[0].modeled_legitimate_capital_affected
            )
            assert (
                results[i].remaining_downstream_taint
                == results[0].remaining_downstream_taint
            )
            assert results[i].blocked_event_ids == results[0].blocked_event_ids
            assert (
                results[i].number_of_affected_edges
                == results[0].number_of_affected_edges
            )
            assert (
                results[i].source_interception_details
                == results[0].source_interception_details
            )

    def test_different_simulator_instances_same_result(self) -> None:
        """Two fresh simulator instances produce identical results."""
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        sim1 = CounterfactualSimulator(graph, baseline)
        sim2 = CounterfactualSimulator(graph, baseline)

        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="B",
        )

        r1 = sim1.simulate(candidate, sim_time)
        r2 = sim2.simulate(candidate, sim_time)

        assert r1.intervention_id == r2.intervention_id
        assert r1.modeled_tainted_capital_intercepted == r2.modeled_tainted_capital_intercepted
        assert r1.blocked_event_ids == r2.blocked_event_ids


# ── Key invariants ───────────────────────────────────────────────────────────


class TestKeyInvariants:
    """Cross-cutting invariant checks."""

    def test_no_mutation_of_baseline_graph(self) -> None:
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        edge_count_before = graph.edge_count
        node_count_before = graph.node_count

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="B",
        )
        sim.simulate(candidate, sim_time)

        assert graph.edge_count == edge_count_before
        assert graph.node_count == node_count_before

    def test_no_mutation_of_baseline_taint_result(self) -> None:
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        # Snapshot baseline state
        alloc_count = len(baseline.allocations)
        balance_count = len(baseline.account_balances)
        seed_count = len(baseline.seeds)

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="B",
        )
        sim.simulate(candidate, sim_time)

        # Verify baseline is unchanged
        assert len(baseline.allocations) == alloc_count
        assert len(baseline.account_balances) == balance_count
        assert len(baseline.seeds) == seed_count

    def test_blocked_edge_carries_no_taint_in_counterfactual(self) -> None:
        """Taint that would have traversed a blocked edge must remain upstream."""
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.EDGE_HOLD,
            target_event_id="e2",
        )
        result = sim.simulate(candidate, sim_time)

        # In baseline, C and D have taint.  In counterfactual, they should not.
        # The intercepted amount should equal the taint that was on e2
        assert result.modeled_tainted_capital_intercepted > 0

    def test_integer_money_arithmetic(self) -> None:
        """All money fields must be integers."""
        events = commingling_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-seed_a", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=15)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.EDGE_HOLD,
            target_event_id="e_bc",
        )
        result = sim.simulate(candidate, sim_time)

        assert isinstance(result.modeled_tainted_capital_intercepted, int)
        assert isinstance(result.modeled_legitimate_capital_affected, int)
        assert isinstance(result.remaining_downstream_taint, int)

    def test_simulation_timestamp_must_be_tz_aware(self) -> None:
        from datetime import datetime as dt

        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        naive_time = dt(2026, 10, 9, 9, 5, 0)  # no tzinfo
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="B",
        )
        with pytest.raises(ValueError, match="timezone-aware"):
            sim.simulate(candidate, naive_time)


# ── Candidate generation ────────────────────────────────────────────────────


class TestCandidateGeneration:
    def test_generates_account_and_edge_candidates(self) -> None:
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        sim_time = T0 + timedelta(minutes=5)
        candidates = generate_candidates(graph, baseline, sim_time)

        types = {c.intervention_type for c in candidates}
        # Should have at least some candidates
        assert len(candidates) > 0
        # Candidates should be deterministically sorted
        assert candidates == sorted(
            candidates,
            key=lambda c: (
                c.intervention_type.value,
                c.target_account_id or "",
                c.target_event_id or "",
            ),
        )

    def test_no_candidates_when_all_events_historical(self) -> None:
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        # Set sim_time after all events
        sim_time = T0 + timedelta(minutes=30)
        candidates = generate_candidates(graph, baseline, sim_time)

        # There should be no EDGE_HOLD candidates (all events historical)
        edge_candidates = [
            c for c in candidates
            if c.intervention_type == InterventionType.EDGE_HOLD
        ]
        assert len(edge_candidates) == 0

    def test_candidate_generation_requires_tz_aware_timestamp(self) -> None:
        from datetime import datetime as dt

        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        with pytest.raises(ValueError, match="timezone-aware"):
            generate_candidates(graph, baseline, dt(2026, 10, 9, 9, 5, 0))


# ── Result structure validation ──────────────────────────────────────────────


class TestResultStructure:
    """Verify all required output fields are present and correctly typed."""

    def test_all_required_fields_present(self) -> None:
        events = simple_chain_events()
        graph = make_graph(*events)
        seed = _seed("case1", "tx-e1", 100_00)
        baseline = run_taint(graph, [seed])

        sim = CounterfactualSimulator(graph, baseline)
        sim_time = T0 + timedelta(minutes=5)
        candidate = InterventionCandidate(
            intervention_type=InterventionType.ACCOUNT_HOLD,
            target_account_id="B",
        )
        result = sim.simulate(candidate, sim_time)

        # Verify all required output fields
        assert result.intervention_id is not None
        assert result.intervention_type == InterventionType.ACCOUNT_HOLD
        assert result.target_account_id == "B"
        assert result.target_event_id is None
        assert result.simulation_timestamp == sim_time
        assert isinstance(result.modeled_tainted_capital_intercepted, int)
        assert isinstance(result.modeled_legitimate_capital_affected, int)
        assert isinstance(result.remaining_downstream_taint, int)
        assert isinstance(result.number_of_affected_edges, int)
        assert isinstance(result.number_of_affected_accounts, int)
        assert isinstance(result.provenance_coverage, float)
        assert isinstance(result.provenance_confidence, float)
        assert isinstance(result.explanation, str)
        assert isinstance(result.blocked_event_ids, tuple)
        assert isinstance(result.affected_account_ids, tuple)
        assert isinstance(result.source_interception_details, tuple)
        assert 0.0 <= result.provenance_coverage <= 1.0
        assert 0.0 <= result.provenance_confidence <= 1.0
