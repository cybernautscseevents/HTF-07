"""
Tests for the core TemporalGraph — node/edge creation, multigraph
semantics, time-window queries, and active-flow filtering.
"""

from datetime import timedelta

import pytest

from backend.app.graph.temporal_graph import TemporalGraph
from contracts.enums import TransactionStatus

from tests.graph.conftest import (
    T0,
    chain_events,
    fan_out_events,
    make_event,
    mixed_status_events,
)


# ── Node creation ────────────────────────────────────────────────────────────


class TestNodeCreation:
    def test_single_event_creates_two_nodes(self):
        g = TemporalGraph()
        events = [make_event("e1", "t1", "A", "B", occurred_at=T0)]
        g.build_case(events)
        assert g.node_count == 2
        assert g.edge_count == 1
        assert g.has_account("A")
        assert g.has_account("B")

    def test_chain_creates_correct_node_count(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        assert g.node_count == 4  # A, B, C, D
        assert g.edge_count == 3

    def test_shared_accounts_not_duplicated(self):
        g = TemporalGraph()
        g.build_case(fan_out_events())
        # S sends to A, B, C → 4 nodes total
        assert g.node_count == 4
        assert "S" in g.accounts

    def test_add_event_returns_edge_index(self):
        g = TemporalGraph()
        evt = make_event("e1", "t1", "A", "B", occurred_at=T0)
        idx = g.add_event(evt)
        assert isinstance(idx, int)
        assert idx >= 0


# ── Multiple edges between same accounts ────────────────────────────────────


class TestMultiEdge:
    def test_parallel_edges_between_same_pair(self):
        """Multigraph must keep separate edges for each event."""
        g = TemporalGraph()
        g.add_event(make_event("e1", "t1", "A", "B",
                               occurred_at=T0, amount=100_00))
        g.add_event(make_event("e2", "t2", "A", "B",
                               occurred_at=T0 + timedelta(minutes=5),
                               amount=200_00))
        assert g.node_count == 2
        assert g.edge_count == 2

        outgoing = g.outgoing("A", active_only=False)
        assert len(outgoing) == 2
        amounts = {e.amount_minor_units for e in outgoing}
        assert amounts == {100_00, 200_00}

    def test_bidirectional_edges(self):
        """A→B and B→A are separate directed edges."""
        g = TemporalGraph()
        g.add_event(make_event("e1", "t1", "A", "B", occurred_at=T0))
        g.add_event(make_event("e2", "t2", "B", "A",
                               occurred_at=T0 + timedelta(minutes=1)))
        assert g.edge_count == 2
        assert len(g.outgoing("A", active_only=False)) == 1
        assert len(g.outgoing("B", active_only=False)) == 1
        assert len(g.incoming("A", active_only=False)) == 1
        assert len(g.incoming("B", active_only=False)) == 1


# ── Chronological ordering ──────────────────────────────────────────────────


class TestChronologicalOrdering:
    def test_outgoing_edges_sorted_by_time(self):
        g = TemporalGraph()
        g.add_event(make_event("e3", "t3", "A", "D",
                               occurred_at=T0 + timedelta(minutes=20)))
        g.add_event(make_event("e1", "t1", "A", "B",
                               occurred_at=T0))
        g.add_event(make_event("e2", "t2", "A", "C",
                               occurred_at=T0 + timedelta(minutes=10)))

        outgoing = g.outgoing("A", active_only=False)
        times = [e.occurred_at for e in outgoing]
        assert times == sorted(times)

    def test_incoming_edges_sorted_by_time(self):
        g = TemporalGraph()
        g.add_event(make_event("e2", "t2", "B", "T",
                               occurred_at=T0 + timedelta(minutes=10)))
        g.add_event(make_event("e1", "t1", "A", "T",
                               occurred_at=T0))

        incoming = g.incoming("T", active_only=False)
        times = [e.occurred_at for e in incoming]
        assert times == sorted(times)


# ── Incoming / outgoing queries ──────────────────────────────────────────────


class TestIncomingOutgoing:
    def test_outgoing_from_chain_start(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        out_a = g.outgoing("A")
        assert len(out_a) == 1
        assert out_a[0].receiver_id == "B"

    def test_incoming_to_chain_end(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        inc_d = g.incoming("D")
        assert len(inc_d) == 1
        assert inc_d[0].sender_id == "C"

    def test_no_outgoing_for_terminal_node(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        assert len(g.outgoing("D")) == 0

    def test_no_incoming_for_source_node(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        assert len(g.incoming("A")) == 0


# ── Time-window filtering ───────────────────────────────────────────────────


class TestTimeWindowFiltering:
    def test_events_between_full_range(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        all_events = g.events_between()
        assert len(all_events) == 3

    def test_events_between_narrow_window(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        # Only the second event (T0+10min)
        window = g.events_between(
            start=T0 + timedelta(minutes=5),
            end=T0 + timedelta(minutes=15),
        )
        assert len(window) == 1
        assert window[0].event_id == "e2"

    def test_outgoing_with_time_filter(self):
        g = TemporalGraph()
        g.build_case(fan_out_events())
        # Only events from S after minute 1
        out = g.outgoing("S", start=T0 + timedelta(minutes=1))
        event_ids = {e.event_id for e in out}
        assert "fo1" not in event_ids
        assert "fo2" in event_ids
        assert "fo3" in event_ids


# ── Active-flow filtering (pending/failed/reversed exclusion) ────────────────


class TestActiveFlowFiltering:
    def test_active_only_excludes_pending(self):
        g = TemporalGraph()
        g.build_case(mixed_status_events())
        active = g.outgoing("A", active_only=True)
        statuses = {e.status for e in active}
        assert TransactionStatus.PENDING not in statuses

    def test_active_only_excludes_failed(self):
        g = TemporalGraph()
        g.build_case(mixed_status_events())
        active = g.outgoing("A", active_only=True)
        statuses = {e.status for e in active}
        assert TransactionStatus.FAILED not in statuses

    def test_active_only_excludes_reversed(self):
        g = TemporalGraph()
        g.build_case(mixed_status_events())
        active = g.outgoing("A", active_only=True)
        statuses = {e.status for e in active}
        assert TransactionStatus.REVERSED not in statuses

    def test_active_only_keeps_completed(self):
        g = TemporalGraph()
        g.build_case(mixed_status_events())
        active = g.outgoing("A", active_only=True)
        assert len(active) == 2  # ms1 and ms5
        assert all(e.status == TransactionStatus.COMPLETED for e in active)

    def test_all_statuses_visible_when_not_active_only(self):
        g = TemporalGraph()
        g.build_case(mixed_status_events())
        all_edges = g.outgoing("A", active_only=False)
        assert len(all_edges) == 5

    def test_reversed_event_retained_in_storage(self):
        """Reversed events are stored; they just don't count as active flow."""
        g = TemporalGraph()
        g.build_case(mixed_status_events())
        reversed_edge = g.get_edge_by_event("ms4")
        assert reversed_edge.status == TransactionStatus.REVERSED
        assert not reversed_edge.is_active_flow


# ── Edge lookup ──────────────────────────────────────────────────────────────


class TestEdgeLookup:
    def test_get_edge_by_event_id(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        edge = g.get_edge_by_event("e2")
        assert edge.sender_id == "B"
        assert edge.receiver_id == "C"
        assert edge.transaction_id == "t2"

    def test_missing_event_raises(self):
        g = TemporalGraph()
        with pytest.raises(KeyError):
            g.get_edge_by_event("nonexistent")
