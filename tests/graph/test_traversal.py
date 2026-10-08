"""
Tests for temporal traversal algorithms — downstream BFS and path discovery.
"""

from datetime import timedelta

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.graph.traversal import find_temporal_paths, temporal_downstream
from contracts.enums import TransactionStatus

from tests.graph.conftest import (
    T0,
    chain_events,
    fan_out_events,
    make_event,
    mixed_status_events,
)


# ── Temporal downstream (BFS) ───────────────────────────────────────────────


class TestTemporalDownstream:
    def test_chain_full_downstream(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        result = temporal_downstream(g, "A")
        # A→B, B→C, C→D → 3 edges
        assert len(result) == 3
        event_ids = [e.event_id for e, _ in result]
        assert event_ids == ["e1", "e2", "e3"]

    def test_chain_downstream_depths(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        result = temporal_downstream(g, "A")
        depths = [d for _, d in result]
        assert depths == [1, 2, 3]

    def test_downstream_with_max_depth(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        result = temporal_downstream(g, "A", max_depth=2)
        assert len(result) == 2
        event_ids = [e.event_id for e, _ in result]
        assert "e3" not in event_ids

    def test_downstream_with_start_time(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        # Start at T0+10min — skip e1, start from B→C
        result = temporal_downstream(g, "A", start_time=T0 + timedelta(minutes=10))
        # A has no outgoing with occurred_at >= T0+10min
        # (A→B is at T0+0min) — so nothing found from A after T0+10min
        assert len(result) == 0

    def test_downstream_from_middle_of_chain(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        result = temporal_downstream(g, "B")
        # B→C at T0+10, C→D at T0+20
        assert len(result) == 2

    def test_downstream_from_terminal_node(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        result = temporal_downstream(g, "D")
        assert len(result) == 0

    def test_downstream_excludes_inactive_edges(self):
        g = TemporalGraph()
        g.build_case(mixed_status_events())
        # A has outgoing: completed(B), pending(C), failed(D), reversed(E), completed(F)
        result = temporal_downstream(g, "A")
        # Only completed edges: A→B (ms1), A→F (ms5)
        event_ids = {e.event_id for e, _ in result}
        assert event_ids == {"ms1", "ms5"}

    def test_downstream_fan_out(self):
        g = TemporalGraph()
        g.build_case(fan_out_events())
        result = temporal_downstream(g, "S")
        assert len(result) == 3  # S→A, S→B, S→C


# ── Temporal path discovery (DFS) ───────────────────────────────────────────


class TestFindTemporalPaths:
    def test_chain_path_found(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        paths = find_temporal_paths(g, "A", "D")
        assert len(paths) == 1
        assert len(paths[0]) == 3  # 3 edges: A→B, B→C, C→D

    def test_chain_path_is_chronological(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        paths = find_temporal_paths(g, "A", "D")
        path = paths[0]
        times = [e.occurred_at for e in path]
        # Strictly increasing
        for i in range(1, len(times)):
            assert times[i] > times[i - 1]

    def test_no_path_when_unreachable(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        paths = find_temporal_paths(g, "D", "A")  # reverse — no temporal path
        assert len(paths) == 0

    def test_direct_path(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        paths = find_temporal_paths(g, "A", "B")
        assert len(paths) == 1
        assert len(paths[0]) == 1

    def test_max_depth_limits_path_length(self):
        g = TemporalGraph()
        g.build_case(chain_events())
        paths = find_temporal_paths(g, "A", "D", max_depth=2)
        # Path A→D requires 3 hops, depth 2 is not enough
        assert len(paths) == 0

    def test_multiple_paths_via_parallel_edges(self):
        """Two parallel edges from A to B, one continuing B→C."""
        g = TemporalGraph()
        g.add_event(make_event("p1", "t1", "A", "B",
                               occurred_at=T0))
        g.add_event(make_event("p2", "t2", "A", "B",
                               occurred_at=T0 + timedelta(minutes=5)))
        g.add_event(make_event("p3", "t3", "B", "C",
                               occurred_at=T0 + timedelta(minutes=10)))

        paths = find_temporal_paths(g, "A", "C")
        # Two paths: p1→p3 and p2→p3
        assert len(paths) == 2

    def test_path_excludes_inactive_edges(self):
        """Pending/failed/reversed edges should not appear in paths."""
        g = TemporalGraph()
        # A → B (pending) → C (completed) — no valid path through pending
        g.add_event(make_event("x1", "tx1", "A", "B",
                               occurred_at=T0,
                               status=TransactionStatus.PENDING))
        g.add_event(make_event("x2", "tx2", "B", "C",
                               occurred_at=T0 + timedelta(minutes=10)))

        paths = find_temporal_paths(g, "A", "C")
        assert len(paths) == 0

    def test_path_through_completed_chain(self):
        """A completed chain should be fully traversable."""
        g = TemporalGraph()
        g.add_event(make_event("c1", "tc1", "A", "B",
                               occurred_at=T0))
        g.add_event(make_event("c2", "tc2", "B", "C",
                               occurred_at=T0 + timedelta(minutes=5)))
        paths = find_temporal_paths(g, "A", "C")
        assert len(paths) == 1
        assert all(e.status == TransactionStatus.COMPLETED for e in paths[0])
