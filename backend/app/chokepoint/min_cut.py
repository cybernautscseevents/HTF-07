"""Deterministic Dinic's algorithm and temporal minimum-cut extraction.

Computes the exact minimum s-t cut on a time-expanded directed network
using integer capacity arithmetic.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Sequence

from backend.app.chokepoint.models import (
    ChokepointStatus,
    TemporalCutEdge,
)
from backend.app.chokepoint.temporal_network import TimeExpandedNetwork


@dataclass
class _ResidualEdge:
    """An edge in the residual flow graph."""

    to_node: int
    rev_index: int
    capacity: int
    flow: int
    arc_id: int | None


class DinicSolver:
    """Deterministic implementation of Dinic's algorithm for maximum flow / minimum cut."""

    def __init__(self, num_nodes: int, source: int, sink: int) -> None:
        self._num_nodes = num_nodes
        self._source = source
        self._sink = sink
        self._adj: list[list[_ResidualEdge]] = [[] for _ in range(num_nodes)]
        self._level: list[int] = [-1] * num_nodes
        self._ptr: list[int] = [0] * num_nodes

    def add_edge(self, from_node: int, to_node: int, capacity: int, arc_id: int | None = None) -> None:
        """Add a directed edge with forward capacity and zero reverse capacity."""
        forward_idx = len(self._adj[from_node])
        reverse_idx = len(self._adj[to_node])
        if from_node == to_node:
            reverse_idx += 1  # self-loop edge indexing adjustment if any

        fwd_edge = _ResidualEdge(
            to_node=to_node,
            rev_index=reverse_idx,
            capacity=capacity,
            flow=0,
            arc_id=arc_id,
        )
        rev_edge = _ResidualEdge(
            to_node=from_node,
            rev_index=forward_idx,
            capacity=0,
            flow=0,
            arc_id=None,
        )
        self._adj[from_node].append(fwd_edge)
        self._adj[to_node].append(rev_edge)

    def _bfs_level_graph(self) -> bool:
        """Compute vertex levels from source in residual network."""
        self._level = [-1] * self._num_nodes
        self._level[self._source] = 0
        queue: deque[int] = deque([self._source])

        while queue:
            u = queue.popleft()
            for edge in self._adj[u]:
                if edge.capacity - edge.flow > 0 and self._level[edge.to_node] == -1:
                    self._level[edge.to_node] = self._level[u] + 1
                    queue.append(edge.to_node)

        return self._level[self._sink] != -1

    def _dfs_blocking_flow(self, u: int, pushed: int) -> int:
        """Push blocking flow along level graph arcs."""
        if u == self._sink or pushed == 0:
            return pushed

        while self._ptr[u] < len(self._adj[u]):
            edge = self._adj[u][self._ptr[u]]
            if self._level[edge.to_node] == self._level[u] + 1 and edge.capacity - edge.flow > 0:
                available = edge.capacity - edge.flow
                flow_to_push = available if pushed > available else pushed
                tr = self._dfs_blocking_flow(edge.to_node, flow_to_push)
                if tr > 0:
                    edge.flow += tr
                    rev_edge = self._adj[edge.to_node][edge.rev_index]
                    rev_edge.flow -= tr
                    return tr
            self._ptr[u] += 1

        return 0

    def compute_max_flow(self) -> int:
        """Execute Dinic's algorithm to compute the exact maximum s-t flow."""
        max_flow = 0
        inf_flow = 1 << 60  # Large integer sentinel

        while self._bfs_level_graph():
            self._ptr = [0] * self._num_nodes
            while True:
                pushed = self._dfs_blocking_flow(self._source, inf_flow)
                if pushed <= 0:
                    break
                max_flow += pushed

        return max_flow

    def get_source_reachable_set(self) -> set[int]:
        """Return the deterministic set S* of vertices reachable from source in residual graph.

        The cut (S*, V \\ S*) corresponds to the canonical source-closest minimum cut.
        """
        visited: set[int] = {self._source}
        queue: deque[int] = deque([self._source])

        while queue:
            u = queue.popleft()
            # Iterate in deterministic edge order
            for edge in self._adj[u]:
                if edge.capacity - edge.flow > 0 and edge.to_node not in visited:
                    visited.add(edge.to_node)
                    queue.append(edge.to_node)

        return visited


def compute_temporal_min_cut(
    network: TimeExpandedNetwork,
) -> tuple[ChokepointStatus, tuple[TemporalCutEdge, ...], int, int]:
    """Compute the minimum-cost temporal cut disconnecting sources from sinks.

    Parameters
    ----------
    network : TimeExpandedNetwork
        The sparse time-expanded causal network.

    Returns
    -------
    tuple[ChokepointStatus, tuple[TemporalCutEdge, ...], int, int]
        - Status (OPTIMAL_CUT_FOUND, NO_PATH_EXISTS, or NO_FEASIBLE_CUT)
        - Tuple of TemporalCutEdge members forming the cut
        - Total encoded cut cost
        - Total estimated legitimate collateral (paise)
    """
    solver = DinicSolver(
        num_nodes=network.num_nodes,
        source=network.source_node,
        sink=network.sink_node,
    )

    for arc in network.arcs:
        solver.add_edge(arc.from_node, arc.to_node, arc.capacity, arc_id=arc.arc_id)

    max_flow = solver.compute_max_flow()

    # 1. No path exists initially between sources and sinks
    if max_flow == 0:
        return (
            ChokepointStatus.NO_PATH_EXISTS,
            (),
            0,
            0,
        )

    # 2. Flow reaches or exceeds inf_capacity: an infinite-capacity arc would have to be cut.
    # Hence no cut of solely eligible edges can disconnect the source from the sink.
    if max_flow >= network.inf_capacity:
        return (
            ChokepointStatus.NO_FEASIBLE_CUT,
            (),
            max_flow,
            0,
        )

    # 3. Feasible minimum cut found
    reachable_nodes = solver.get_source_reachable_set()

    cut_edges_list: list[TemporalCutEdge] = []
    total_collateral = 0
    total_encoded_cost = 0

    # Locate saturated arcs that cross from S* to V \ S*
    # We inspect the cuttable arcs corresponding to eligible transaction edges
    for arc in network.arcs:
        if arc.is_cuttable and arc.event_id is not None:
            if arc.from_node in reachable_nodes and arc.to_node not in reachable_nodes:
                event_norm = network.event_lookup[arc.event_id]
                collateral = network.event_collateral.get(arc.event_id, 0)
                cut_edges_list.append(
                    TemporalCutEdge(
                        event_id=event_norm.event_id,
                        transaction_id=event_norm.transaction_id,
                        sender_account_id=event_norm.sender_account_id,
                        receiver_account_id=event_norm.receiver_account_id,
                        amount_minor_units=event_norm.amount_minor_units,
                        occurred_at=event_norm.occurred_at,
                        estimated_legitimate_collateral_minor_units=collateral,
                        encoded_capacity=arc.capacity,
                        is_forecast=event_norm.is_forecast,
                    )
                )
                total_collateral += collateral
                total_encoded_cost += arc.capacity

    # Deterministic canonical sort by (occurred_at, event_id)
    cut_edges_list.sort(key=lambda edge: (edge.occurred_at, edge.event_id))

    return (
        ChokepointStatus.OPTIMAL_CUT_FOUND,
        tuple(cut_edges_list),
        total_encoded_cost,
        total_collateral,
    )
