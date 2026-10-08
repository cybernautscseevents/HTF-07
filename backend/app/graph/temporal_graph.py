"""
TemporalGraph — directed temporal multigraph for financial flow analysis.

Wraps a :class:`rustworkx.PyDiGraph` (with ``multigraph=True``) where:

* **Nodes** = accounts, identified by opaque ``account_id`` strings.
* **Edges** = transaction events.  Each :class:`TransactionEvent` becomes
  a separate directed edge, even when the same account pair has multiple
  transactions.  Edge payloads are :class:`EdgeData` frozen dataclasses.

The graph is purely computational — it carries no rendering, persistence,
or business logic.  Taint propagation, scoring, and intervention are
handled by downstream engines that consume this graph.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

import rustworkx as rx

from contracts.transaction import TransactionEvent
from backend.app.graph.temporal_index import EdgeData, TemporalIndex


class TemporalGraph:
    """Directed temporal multigraph over financial accounts and events.

    This is the core data structure consumed by traversal, motif
    detection, and (later) taint-propagation algorithms.
    """

    def __init__(self) -> None:
        self._graph: rx.PyDiGraph = rx.PyDiGraph(multigraph=True)
        self._account_to_node: dict[str, int] = {}
        self._event_to_edge: dict[str, int] = {}
        self._index = TemporalIndex()

    # ── Node management ──────────────────────────────────────────────────

    def _get_or_create_node(self, account_id: str) -> int:
        """Return the rustworkx node index for *account_id*, creating it
        if it does not already exist."""
        if account_id in self._account_to_node:
            return self._account_to_node[account_id]
        idx = self._graph.add_node(account_id)
        self._account_to_node[account_id] = idx
        return idx

    def has_account(self, account_id: str) -> bool:
        """Check whether an account exists as a node in the graph."""
        return account_id in self._account_to_node

    # ── Event ingestion ──────────────────────────────────────────────────

    def add_event(self, event: TransactionEvent) -> int:
        """Ingest a single :class:`TransactionEvent` as a directed edge.

        Returns the rustworkx edge index.
        """
        sender_idx = self._get_or_create_node(event.sender.account_id)
        receiver_idx = self._get_or_create_node(event.receiver.account_id)

        edge_data = EdgeData(
            event_id=event.event_id,
            transaction_id=event.transaction_id,
            amount_minor_units=event.amount_minor_units,
            currency=event.currency,
            occurred_at=event.occurred_at,
            observed_at=event.observed_at,
            status=event.status,
            channel=event.channel,
            origin=event.origin,
            sender_id=event.sender.account_id,
            receiver_id=event.receiver.account_id,
        )

        edge_idx = self._graph.add_edge(sender_idx, receiver_idx, edge_data)
        self._event_to_edge[event.event_id] = edge_idx
        self._index.add(edge_idx, edge_data)
        return edge_idx

    def build_case(self, events: Iterable[TransactionEvent]) -> None:
        """Batch-ingest events (e.g. all events associated with a fraud case)."""
        for event in events:
            self.add_event(event)

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def node_count(self) -> int:
        """Number of distinct accounts (nodes) in the graph."""
        return self._graph.num_nodes()

    @property
    def edge_count(self) -> int:
        """Total number of event edges in the graph."""
        return self._graph.num_edges()

    @property
    def accounts(self) -> list[str]:
        """All account IDs present as nodes."""
        return list(self._account_to_node.keys())

    # ── Edge lookup ──────────────────────────────────────────────────────

    def get_edge_by_event(self, event_id: str) -> EdgeData:
        """Look up edge data by canonical ``event_id``."""
        edge_idx = self._event_to_edge[event_id]
        return self._index.get_edge(edge_idx)

    # ── Temporal queries (delegated to index) ────────────────────────────

    def outgoing(
        self,
        account_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        active_only: bool = True,
    ) -> list[EdgeData]:
        """Outgoing edges from *account_id*, optionally filtered by time
        window ``[start, end]`` and active-flow status."""
        return self._index.outgoing(account_id, start, end, active_only)

    def incoming(
        self,
        account_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        active_only: bool = True,
    ) -> list[EdgeData]:
        """Incoming edges to *account_id*, optionally filtered by time
        window ``[start, end]`` and active-flow status."""
        return self._index.incoming(account_id, start, end, active_only)

    def events_between(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        active_only: bool = True,
    ) -> list[EdgeData]:
        """All edges with ``occurred_at`` in ``[start, end]``."""
        return self._index.events_between(start, end, active_only)
