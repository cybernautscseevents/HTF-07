"""In-memory registry of per-case temporal graphs."""

from __future__ import annotations

from collections.abc import Iterable

from contracts.transaction import TransactionEvent

from backend.app.graph.temporal_graph import TemporalGraph


class CaseGraphRegistry:
    """Maintain an isolated :class:`TemporalGraph` for each case ID."""

    def __init__(self) -> None:
        self._graphs: dict[str, TemporalGraph] = {}
        self._event_ids: dict[str, set[str]] = {}

    def get(self, case_id: str) -> TemporalGraph | None:
        """Return the graph for *case_id*, if it has been created."""
        return self._graphs.get(case_id)

    def get_or_create(self, case_id: str) -> TemporalGraph:
        """Return the graph for *case_id*, creating an empty one if needed."""
        graph = self._graphs.get(case_id)
        if graph is None:
            graph = TemporalGraph()
            self._graphs[case_id] = graph
            self._event_ids[case_id] = set()
        return graph

    def add_event(self, case_id: str, event: TransactionEvent) -> None:
        """Add an event to its case graph once, preserving graph semantics."""
        seen_event_ids = self._event_ids.setdefault(case_id, set())
        if event.event_id in seen_event_ids:
            return
        self.get_or_create(case_id).add_event(event)
        seen_event_ids.add(event.event_id)

    def add_events(
        self, case_id: str, events: Iterable[TransactionEvent]
    ) -> None:
        """Add a persisted batch to its case graph in submission order."""
        for event in events:
            self.add_event(case_id, event)

    def graph(self, case_id: str) -> TemporalGraph | None:
        """Return the actual temporal graph for *case_id*, if it exists."""
        return self.get(case_id)
