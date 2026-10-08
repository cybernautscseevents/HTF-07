"""
Temporal traversal algorithms over the financial flow graph.

All traversals respect the **active-flow rule** (only ``completed``
edges) and enforce **strictly increasing** ``occurred_at`` for causal
ordering — money cannot arrive at hop N+1 before it departs hop N.

Strictly increasing time also inherently prevents temporal cycles.

Timestamp semantics (MVP causality rule)
----------------------------------------
* ``temporal_downstream`` and ``find_temporal_paths`` both require
  **strictly increasing** ``occurred_at`` timestamps between causal
  hops (i.e. ``next_edge.occurred_at > current_edge.occurred_at``).
* This conservative rule **prevents the system from inferring causal
  flow between simultaneous events** with identical ``occurred_at``
  timestamps.  Two events at the exact same ``occurred_at`` are never
  treated as causally linked, even if real-world settlement ordering
  might allow it.
* This is an **MVP causality rule**, not a claim about real-world
  settlement ordering.  Future versions may introduce sub-second
  sequence numbers or institution-specific settlement semantics to
  relax this constraint.

Complexity
----------
* ``temporal_downstream`` — Each BFS step queries outgoing edges via
  the temporal index: O(log E + k_a) per node visited, where k_a is
  the outgoing edge count for that account.  Total cost over the full
  traversal is O(R · (log E + k_a)) where R is the number of result
  edges discovered.  Each edge is dequeued at most once.
* ``find_temporal_paths`` — O(V! / (V−d)!) in the worst case for
  depth *d* in a complete graph, but bounded by ``max_depth`` and the
  monotonic-time constraint which aggressively prunes the search space.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from backend.app.graph.temporal_index import EdgeData

if TYPE_CHECKING:
    from backend.app.graph.temporal_graph import TemporalGraph

# Minimum possible datetime — used as default start when none is given.
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def temporal_downstream(
    graph: TemporalGraph,
    start_account_id: str,
    start_time: datetime | None = None,
    max_depth: int | None = None,
) -> list[tuple[EdgeData, int]]:
    """BFS downstream traversal from *start_account_id*.

    Follows only **active** edges (``completed``) with **strictly
    increasing** ``occurred_at`` at each hop.

    Parameters
    ----------
    graph : TemporalGraph
        The temporal multigraph to traverse.
    start_account_id : str
        Account from which to begin the downstream search.
    start_time : datetime, optional
        If given, only edges with ``occurred_at >= start_time`` are
        considered for the first hop.
    max_depth : int, optional
        Maximum number of hops from the start.  ``None`` means no limit.

    Returns
    -------
    list[tuple[EdgeData, int]]
        Each element is ``(edge, depth)`` where *depth* is the hop
        distance from *start_account_id*.  Results are ordered by BFS
        discovery.
    """
    visited_events: set[str] = set()
    results: list[tuple[EdgeData, int]] = []

    # Seed the queue with all qualifying outgoing edges from start.
    seed_edges = graph.outgoing(
        start_account_id, start=start_time, active_only=True,
    )
    queue: deque[tuple[EdgeData, int]] = deque()
    for edge in seed_edges:
        queue.append((edge, 1))

    while queue:
        edge, depth = queue.popleft()

        if edge.event_id in visited_events:
            continue
        if max_depth is not None and depth > max_depth:
            continue

        visited_events.add(edge.event_id)
        results.append((edge, depth))

        # Expand: outgoing from receiver with strictly later time.
        next_edges = graph.outgoing(
            edge.receiver_id, start=edge.occurred_at, active_only=True,
        )
        for next_edge in next_edges:
            if (
                next_edge.occurred_at > edge.occurred_at
                and next_edge.event_id not in visited_events
            ):
                queue.append((next_edge, depth + 1))

    return results


def find_temporal_paths(
    graph: TemporalGraph,
    source_id: str,
    target_id: str,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    max_depth: int = 10,
) -> list[list[EdgeData]]:
    """Find all simple temporal paths from *source_id* to *target_id*.

    Each path is a sequence of edges with **strictly increasing**
    ``occurred_at``.  Paths are *simple* — no account is visited twice.

    Parameters
    ----------
    graph : TemporalGraph
        The temporal multigraph to search.
    source_id, target_id : str
        Source and destination account IDs.
    start_time, end_time : datetime, optional
        Restrict the search window.
    max_depth : int
        Maximum path length (number of edges).

    Returns
    -------
    list[list[EdgeData]]
        Each inner list is a complete path from source to target.
    """
    paths: list[list[EdgeData]] = []

    init_time = start_time if start_time is not None else _EPOCH

    def _dfs(
        current_account: str,
        current_time: datetime,
        path: list[EdgeData],
        visited_accounts: set[str],
    ) -> None:
        if current_account == target_id and path:
            paths.append(list(path))
            return

        if len(path) >= max_depth:
            return

        outgoing = graph.outgoing(
            current_account,
            start=current_time,
            end=end_time,
            active_only=True,
        )

        for edge in outgoing:
            if edge.occurred_at <= current_time:
                continue  # strictly increasing
            if edge.receiver_id in visited_accounts:
                continue  # simple paths only

            path.append(edge)
            visited_accounts.add(edge.receiver_id)
            _dfs(edge.receiver_id, edge.occurred_at, path, visited_accounts)
            path.pop()
            visited_accounts.discard(edge.receiver_id)

    visited: set[str] = {source_id}
    _dfs(source_id, init_time, [], visited)

    return paths
