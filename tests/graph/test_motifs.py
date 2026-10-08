"""
Tests for structural motif detection — fan-out, fan-in, rapid
pass-through, and the compound fan-out → fan-in pattern.
"""

from datetime import timedelta

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.graph.motifs import (
    detect_fan_out,
    detect_fan_in,
    detect_rapid_pass_through,
    detect_fan_out_fan_in,
)
from contracts.enums import TransactionStatus

from tests.graph.conftest import (
    T0,
    chain_events,
    fan_in_events,
    fan_out_events,
    fan_out_fan_in_events,
    make_event,
    pass_through_events,
)


# ── Fan-out detection ────────────────────────────────────────────────────────


class TestFanOut:
    def test_detects_fan_out(self):
        g = TemporalGraph()
        g.build_case(fan_out_events())  # S → A, B, C
        results = detect_fan_out(g, window_seconds=600, min_targets=3)
        assert len(results) == 1
        assert results[0].source == "S"
        assert results[0].targets == frozenset({"A", "B", "C"})

    def test_no_fan_out_below_threshold(self):
        g = TemporalGraph()
        g.build_case(fan_out_events())
        results = detect_fan_out(g, window_seconds=600, min_targets=4)
        assert len(results) == 0

    def test_no_fan_out_outside_window(self):
        g = TemporalGraph()
        g.add_event(make_event("w1", "t1", "S", "A", occurred_at=T0))
        g.add_event(make_event("w2", "t2", "S", "B",
                               occurred_at=T0 + timedelta(hours=2)))
        g.add_event(make_event("w3", "t3", "S", "C",
                               occurred_at=T0 + timedelta(hours=4)))
        # Window of 60s — too small
        results = detect_fan_out(g, window_seconds=60, min_targets=3)
        assert len(results) == 0

    def test_fan_out_ignores_inactive_edges(self):
        g = TemporalGraph()
        g.add_event(make_event("f1", "t1", "S", "A", occurred_at=T0))
        g.add_event(make_event("f2", "t2", "S", "B",
                               occurred_at=T0 + timedelta(minutes=1),
                               status=TransactionStatus.PENDING))
        g.add_event(make_event("f3", "t3", "S", "C",
                               occurred_at=T0 + timedelta(minutes=2)))
        # Only 2 active → no fan-out at min_targets=3
        results = detect_fan_out(g, window_seconds=600, min_targets=3)
        assert len(results) == 0

    def test_chain_has_no_fan_out(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        results = detect_fan_out(g, window_seconds=3600, min_targets=2)
        assert len(results) == 0


# ── Fan-in detection ─────────────────────────────────────────────────────────


class TestFanIn:
    def test_detects_fan_in(self):
        g = TemporalGraph()
        g.build_case(fan_in_events())  # A, B, C → T
        results = detect_fan_in(g, window_seconds=600, min_sources=3)
        assert len(results) == 1
        assert results[0].target == "T"
        assert results[0].sources == frozenset({"A", "B", "C"})

    def test_no_fan_in_below_threshold(self):
        g = TemporalGraph()
        g.build_case(fan_in_events())
        results = detect_fan_in(g, window_seconds=600, min_sources=4)
        assert len(results) == 0

    def test_fan_in_ignores_inactive_edges(self):
        g = TemporalGraph()
        g.add_event(make_event("i1", "t1", "A", "T", occurred_at=T0))
        g.add_event(make_event("i2", "t2", "B", "T",
                               occurred_at=T0 + timedelta(minutes=1),
                               status=TransactionStatus.FAILED))
        g.add_event(make_event("i3", "t3", "C", "T",
                               occurred_at=T0 + timedelta(minutes=2)))
        results = detect_fan_in(g, window_seconds=600, min_sources=3)
        assert len(results) == 0

    def test_chain_has_no_fan_in(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        results = detect_fan_in(g, window_seconds=3600, min_sources=2)
        assert len(results) == 0


# ── Rapid pass-through detection ─────────────────────────────────────────────


class TestRapidPassThrough:
    def test_detects_pass_through(self):
        g = TemporalGraph()
        g.build_case(pass_through_events())  # A → P → B, 30s delay
        results = detect_rapid_pass_through(g, max_delay_seconds=60)
        assert len(results) >= 1
        pt = results[0]
        assert pt.account == "P"
        assert pt.delay_seconds == 30.0

    def test_no_pass_through_if_delay_too_long(self):
        g = TemporalGraph()
        g.build_case(pass_through_events())  # 30s delay
        results = detect_rapid_pass_through(g, max_delay_seconds=10)
        assert len(results) == 0

    def test_no_pass_through_for_terminal_node(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        # D has no outgoing → no pass-through
        results = detect_rapid_pass_through(g, max_delay_seconds=3600)
        pt_accounts = {r.account for r in results}
        assert "D" not in pt_accounts
        assert "A" not in pt_accounts  # A has no incoming

    def test_pass_through_in_chain(self):
        """B and C are pass-through nodes in A→B→C→D."""
        g = TemporalGraph()
        g.build_case(chain_events())
        results = detect_rapid_pass_through(g, max_delay_seconds=3600)
        pt_accounts = {r.account for r in results}
        assert "B" in pt_accounts
        assert "C" in pt_accounts

    def test_pass_through_ignores_reversed_incoming(self):
        g = TemporalGraph()
        g.add_event(make_event("r1", "t1", "A", "P",
                               occurred_at=T0,
                               status=TransactionStatus.REVERSED))
        g.add_event(make_event("r2", "t2", "P", "B",
                               occurred_at=T0 + timedelta(seconds=10)))
        results = detect_rapid_pass_through(g, max_delay_seconds=60)
        # Reversed incoming is not active → no pass-through
        assert len(results) == 0


# ── Fan-out → fan-in composite motif ────────────────────────────────────────


class TestFanOutFanIn:
    def test_detects_fan_out_fan_in(self):
        g = TemporalGraph()
        g.build_case(fan_out_fan_in_events())
        # S → I1, I2, I3 → T
        results = detect_fan_out_fan_in(
            g, window_seconds=600, min_intermediaries=3,
        )
        assert len(results) == 1
        r = results[0]
        assert r.source == "S"
        assert r.target == "T"
        assert r.intermediaries == frozenset({"I1", "I2", "I3"})

    def test_no_fan_out_fan_in_below_threshold(self):
        g = TemporalGraph()
        g.build_case(fan_out_fan_in_events())
        results = detect_fan_out_fan_in(
            g, window_seconds=600, min_intermediaries=4,
        )
        assert len(results) == 0

    def test_no_fan_out_fan_in_without_convergence(self):
        """Fan-out exists but intermediaries don't converge."""
        g = TemporalGraph()
        g.build_case(fan_out_events())  # S → A, B, C — no convergence
        results = detect_fan_out_fan_in(
            g, window_seconds=600, min_intermediaries=3,
        )
        assert len(results) == 0

    def test_fan_out_fan_in_respects_temporal_order(self):
        """Fan-in edges must occur after fan-out edges."""
        g = TemporalGraph()
        g.build_case(fan_out_fan_in_events())
        results = detect_fan_out_fan_in(
            g, window_seconds=600, min_intermediaries=3,
        )
        r = results[0]
        # All fan-in edges must have occurred_at > fan-out window_start
        for fi_edge in r.fan_in_edges:
            for fo_edge in r.fan_out_edges:
                if fi_edge.sender_id == fo_edge.receiver_id:
                    assert fi_edge.occurred_at > fo_edge.occurred_at
