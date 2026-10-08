"""
Temporal index — time-sorted indexing for efficient temporal range queries.

Maintains sorted edge lists by ``occurred_at`` plus per-account adjacency
lists for incoming/outgoing lookups.

Complexity
----------
* **Insertion** (``add``): O(log E) for binary-search positioning via
  :func:`bisect.insort`, but **O(E) worst-case overall** because
  ``list.insert`` must shift subsequent elements in a Python list.
* **Range queries** (``outgoing``, ``incoming``, ``events_between``):
  O(log E + k) where *k* is the number of results — binary-search to
  locate the window boundaries, then linear scan over the k results.
* **Edge lookup** (``get_edge``): O(1) via ``dict`` lookup.

This module also defines :class:`EdgeData`, the lightweight frozen
dataclass that serves as the internal edge payload throughout the graph
engine.  ``EdgeData`` is extracted from canonical ``TransactionEvent``
objects during ingestion.
"""

from __future__ import annotations

import bisect
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from contracts.enums import (
    EventOrigin,
    TransactionChannel,
    TransactionStatus,
)

# Sentinel for bisect upper-bound queries (larger than any real edge index).
_MAX_EDGE_IDX = sys.maxsize


# ── Edge payload ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class EdgeData:
    """Lightweight, immutable edge payload stored in the temporal graph.

    Extracted from a canonical ``TransactionEvent`` during ingestion.
    Contains only the fields needed for graph computation — no Pydantic
    overhead at query time.
    """

    event_id: str
    transaction_id: str
    amount_minor_units: int
    currency: str
    occurred_at: datetime
    observed_at: datetime
    status: TransactionStatus
    channel: TransactionChannel
    origin: EventOrigin
    sender_id: str
    receiver_id: str

    @property
    def is_active_flow(self) -> bool:
        """Only completed transactions represent active forward flow.

        * ``completed`` → active
        * ``pending``   → not active
        * ``failed``    → not active
        * ``reversed``  → retained but not active forward flow
        """
        return self.status == TransactionStatus.COMPLETED


# ── Temporal index ───────────────────────────────────────────────────────────


class TemporalIndex:
    """Time-sorted index over graph edges.

    Stores ``(occurred_at, edge_index)`` tuples in sorted order for
    the global timeline and per-account adjacency lists.

    * Range queries use :func:`bisect.bisect_left` / ``bisect_right``
      for O(log E + k) lookups.
    * Insertion uses :func:`bisect.insort` — O(log E) search but
      O(E) worst-case overall due to Python ``list.insert`` shifting.
    """

    def __init__(self) -> None:
        self._edges: dict[int, EdgeData] = {}
        self._timeline: list[tuple[datetime, int]] = []
        self._outgoing: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
        self._incoming: dict[str, list[tuple[datetime, int]]] = defaultdict(list)

    # ── Mutation ─────────────────────────────────────────────────────────

    def add(self, edge_idx: int, data: EdgeData) -> None:
        """Register an edge in all index structures."""
        self._edges[edge_idx] = data
        entry = (data.occurred_at, edge_idx)
        bisect.insort(self._timeline, entry)
        bisect.insort(self._outgoing[data.sender_id], entry)
        bisect.insort(self._incoming[data.receiver_id], entry)

    # ── Lookup ───────────────────────────────────────────────────────────

    def get_edge(self, edge_idx: int) -> EdgeData:
        """Look up edge data by rustworkx edge index."""
        return self._edges[edge_idx]

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    # ── Range queries ────────────────────────────────────────────────────

    def _range_query(
        self,
        sorted_entries: list[tuple[datetime, int]],
        start: datetime | None,
        end: datetime | None,
        active_only: bool,
    ) -> list[EdgeData]:
        """Return edge-data objects within ``[start, end]``, optionally
        filtered to active-flow edges only."""
        if not sorted_entries:
            return []

        lo = 0
        if start is not None:
            lo = bisect.bisect_left(sorted_entries, (start,))

        hi = len(sorted_entries)
        if end is not None:
            hi = bisect.bisect_right(sorted_entries, (end, _MAX_EDGE_IDX))

        results: list[EdgeData] = []
        for i in range(lo, hi):
            _, idx = sorted_entries[i]
            edge = self._edges[idx]
            if active_only and not edge.is_active_flow:
                continue
            results.append(edge)
        return results

    def events_between(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        active_only: bool = True,
    ) -> list[EdgeData]:
        """All edges with ``occurred_at`` in ``[start, end]``."""
        return self._range_query(self._timeline, start, end, active_only)

    def outgoing(
        self,
        account_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        active_only: bool = True,
    ) -> list[EdgeData]:
        """Outgoing edges from *account_id* within ``[start, end]``."""
        return self._range_query(
            self._outgoing[account_id], start, end, active_only,
        )

    def incoming(
        self,
        account_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        active_only: bool = True,
    ) -> list[EdgeData]:
        """Incoming edges to *account_id* within ``[start, end]``."""
        return self._range_query(
            self._incoming[account_id], start, end, active_only,
        )
