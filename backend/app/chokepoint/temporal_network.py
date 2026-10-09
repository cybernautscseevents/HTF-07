"""Sparse time-expanded network construction for temporal chokepoint search.

Preserves time-respecting transaction paths without materializing a dense
Cartesian product of accounts and timestamps.

Mathematical Construction & Temporal Correctness
------------------------------------------------
A temporal path P = (e_1, e_2, ..., e_k) is valid if and only if:
    1. e_1.sender in source_account_ids
    2. e_k.receiver in sink_account_ids
    3. For all i in [1, k-1], e_i.receiver == e_{i+1}.sender and
       e_i.occurred_at < e_{i+1}.occurred_at (strictly increasing).

To preserve these exact paths in a directed flow network:
1. Every event e is split into two nodes: (e_in, e_out) connected by a directed
   arc e_in -> e_out. The capacity of this arc is:
   - encoded_cost(e) if e is eligible for intervention.
   - INF_CAPACITY if e is ineligible (e.g. historical, non-compliant, or
     unspecified by policy).
2. For each account v, we collect all distinct timestamps tau_1 < tau_2 < ... < tau_m
   at which transactions enter or leave v. We create timeline nodes (v, tau_k)
   representing capital available at account v *strictly after* timestamp tau_k.
3. Timeline waiting arcs: (v, tau_k) -> (v, tau_{k+1}) with capacity INF_CAPACITY
   model money remaining unspent at account v over time.
4. Inflow arcs: an event e entering account v at tau_k directs flow e_out -> (v, tau_k).
5. Outflow arcs: an event e departing account v at tau_k must draw funds that arrived
   strictly before tau_k. The latest timestamp strictly before tau_k is tau_{k-1}.
   Therefore, flow is fed via (v, tau_{k-1}) -> e_in.
   If k == 1, no money could have arrived at account v before tau_1; hence no incoming
   transfer can causally feed this departure.
6. Source connections: SOURCE connects to e_in for all events departing any
   source account (capacity INF_CAPACITY).
7. Sink connections: e_out connects to SINK for all events arriving at any
   sink account (capacity INF_CAPACITY).

Sparsity & Complexity
---------------------
For E active events across V_A accounts:
- Total event nodes: 2 * E
- Total timeline nodes: <= 2 * E
- Total arcs: <= 7 * E
Both vertex count and arc count scale strictly as O(E). No dense account x time
matrix is materialized.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from contracts.enums import EventOrigin, TransactionStatus
from backend.app.chokepoint.models import ChokepointSearchConfig


class BudgetExceededError(Exception):
    """Raised when active events, vertices, or arcs exceed configured limits."""


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    """Standardized representation of an input event for network construction."""

    event_id: str
    transaction_id: str
    sender_account_id: str
    receiver_account_id: str
    occurred_at: datetime
    amount_minor_units: int
    is_active: bool
    is_forecast: bool


def extract_normalized_event(event: Any) -> NormalizedEvent:
    """Extract standard event fields from TransactionEvent, EdgeData, or ForecastTransactionEvent."""
    event_id = getattr(event, "event_id")
    transaction_id = getattr(event, "transaction_id", event_id)

    # Sender resolution
    sender_id = getattr(event, "sender_id", None)
    if sender_id is None:
        sender_obj = getattr(event, "sender", None)
        sender_id = getattr(sender_obj, "account_id", None)
    if sender_id is None:
        sender_id = getattr(event, "sender_account_id", None)
    if not sender_id:
        raise ValueError(f"Unable to extract sender account ID from event {event_id}.")

    # Receiver resolution
    receiver_id = getattr(event, "receiver_id", None)
    if receiver_id is None:
        receiver_obj = getattr(event, "receiver", None)
        receiver_id = getattr(receiver_obj, "account_id", None)
    if receiver_id is None:
        receiver_id = getattr(event, "receiver_account_id", None)
    if not receiver_id:
        raise ValueError(f"Unable to extract receiver account ID from event {event_id}.")

    occurred_at = getattr(event, "occurred_at")
    if occurred_at.tzinfo is None:
        raise ValueError(f"Event {event_id} occurred_at must be timezone-aware.")

    amount_minor_units = getattr(event, "amount_minor_units")

    # Forecast / active resolution
    is_forecast = (
        getattr(event, "origin", None) == EventOrigin.SYNTHETIC
        or hasattr(event, "probability")
        or getattr(event, "is_forecast", False)
    )

    is_active = getattr(event, "is_active_flow", True)
    if hasattr(event, "status"):
        is_active = (event.status == TransactionStatus.COMPLETED)

    return NormalizedEvent(
        event_id=event_id,
        transaction_id=transaction_id,
        sender_account_id=str(sender_id),
        receiver_account_id=str(receiver_id),
        occurred_at=occurred_at,
        amount_minor_units=int(amount_minor_units),
        is_active=bool(is_active),
        is_forecast=bool(is_forecast),
    )


@dataclass(frozen=True, slots=True)
class NetworkArc:
    """A directed capacity arc in the flow network."""

    arc_id: int
    from_node: int
    to_node: int
    capacity: int
    event_id: str | None = None
    is_cuttable: bool = False


@dataclass(frozen=True, slots=True)
class TimeExpandedNetwork:
    """The constructed sparse time-expanded flow network."""

    num_nodes: int
    source_node: int
    sink_node: int
    arcs: tuple[NetworkArc, ...]
    event_arc_indices: dict[str, int]
    eligible_event_ids: tuple[str, ...]
    ineligible_event_ids: tuple[str, ...]
    total_finite_capacity: int
    inf_capacity: int
    event_lookup: dict[str, NormalizedEvent]
    event_collateral: dict[str, int]


def build_time_expanded_network(
    events: Sequence[Any],
    source_account_ids: Sequence[str],
    sink_account_ids: Sequence[str],
    simulation_timestamp: datetime | None = None,
    eligible_event_ids: Sequence[str] | set[str] | None = None,
    collateral_lookup: Mapping[str, int] | Callable[[str], int] | None = None,
    config: ChokepointSearchConfig | None = None,
) -> TimeExpandedNetwork:
    """Construct a sparse time-expanded network over the provided events.

    Parameters
    ----------
    events : Sequence[Any]
        Collection of transaction events (TransactionEvent, EdgeData, or ForecastTransactionEvent).
    source_account_ids : Sequence[str]
        Account IDs where fraud paths originate.
    sink_account_ids : Sequence[str]
        Account IDs representing exit cash-out destinations.
    simulation_timestamp : datetime, optional
        Decision timestamp. Events occurring at or before this time are historical.
    eligible_event_ids : Sequence[str] | set[str], optional
        Explicit set of event IDs permitted for intervention.
    collateral_lookup : Mapping or Callable, optional
        Lookup returning modeled legitimate capital affected (minor units) per event ID.
    config : ChokepointSearchConfig, optional
        Resource limits and search configuration.

    Returns
    -------
    TimeExpandedNetwork
        Mathematically valid, sparse time-expanded flow network.
    """
    cfg = config or ChokepointSearchConfig()

    # 1. Validate source and sink parameters
    if not source_account_ids:
        raise ValueError("source_account_ids must be non-empty.")
    if not sink_account_ids:
        raise ValueError("sink_account_ids must be non-empty.")

    clean_sources = tuple(str(s).strip() for s in source_account_ids if str(s).strip())
    clean_sinks = tuple(str(d).strip() for d in sink_account_ids if str(d).strip())
    if not clean_sources:
        raise ValueError("source_account_ids contains no valid account IDs.")
    if not clean_sinks:
        raise ValueError("sink_account_ids contains no valid account IDs.")

    source_set = set(clean_sources)
    sink_set = set(clean_sinks)
    overlap = source_set & sink_set
    if overlap:
        raise ValueError(
            f"source_account_ids and sink_account_ids cannot overlap: {sorted(overlap)}"
        )

    if simulation_timestamp is not None and simulation_timestamp.tzinfo is None:
        raise ValueError("simulation_timestamp must be timezone-aware.")

    # 2. Extract and filter active events
    normalized: list[NormalizedEvent] = []
    for raw_event in events:
        norm = extract_normalized_event(raw_event)
        if norm.is_active:
            normalized.append(norm)

    if len(normalized) > cfg.max_active_events:
        raise BudgetExceededError(
            f"Active event count ({len(normalized)}) exceeds maximum allowed "
            f"limit ({cfg.max_active_events})."
        )

    event_lookup: dict[str, NormalizedEvent] = {e.event_id: e for e in normalized}

    # 3. Determine intervention eligibility
    explicit_eligible: set[str] | None = (
        set(eligible_event_ids) if eligible_event_ids is not None else None
    )

    eligible_events: list[NormalizedEvent] = []
    ineligible_events: list[NormalizedEvent] = []

    for e in normalized:
        if explicit_eligible is not None:
            is_eligible = e.event_id in explicit_eligible
        else:
            # Automatic policy: events strictly after simulation_timestamp
            if simulation_timestamp is not None:
                is_eligible = e.occurred_at > simulation_timestamp
            else:
                is_eligible = True

        if is_eligible:
            eligible_events.append(e)
        else:
            ineligible_events.append(e)

    # 4. Compute lexicographic costs for eligible edges
    # N = number of eligible cuttable transaction edges
    # encoded_cost(edge) = collateral_minor_units * (N + 1) + 1
    num_eligible = len(eligible_events)
    multiplier = num_eligible + 1

    event_collateral: dict[str, int] = {}
    event_encoded_cost: dict[str, int] = {}

    for e in eligible_events:
        if collateral_lookup is not None:
            if callable(collateral_lookup):
                collateral = int(collateral_lookup(e.event_id))
            else:
                collateral = int(collateral_lookup.get(e.event_id, 0))
        else:
            collateral = 0

        if collateral < 0:
            raise ValueError(f"Collateral for event {e.event_id} cannot be negative: {collateral}")

        encoded = collateral * multiplier + 1
        event_collateral[e.event_id] = collateral
        event_encoded_cost[e.event_id] = encoded

    total_finite_capacity = sum(event_encoded_cost.values())
    # Infinite capacity is derived strictly greater than all finite cuttable capacities combined
    inf_capacity = total_finite_capacity + 1

    # 5. Build Time-Expanded Graph Topology
    # Node 0: SOURCE
    # Node 1: SINK
    current_node = 2
    SOURCE_NODE = 0
    SINK_NODE = 1

    arcs: list[NetworkArc] = []
    event_arc_indices: dict[str, int] = {}

    def add_arc(from_n: int, to_n: int, cap: int, ev_id: str | None = None, cuttable: bool = False) -> int:
        nonlocal current_node
        if len(arcs) >= cfg.max_expanded_arcs:
            raise BudgetExceededError(
                f"Expanded arc count ({len(arcs) + 1}) exceeds limit ({cfg.max_expanded_arcs})."
            )
        arc_idx = len(arcs)
        arcs.append(NetworkArc(
            arc_id=arc_idx,
            from_node=from_n,
            to_node=to_n,
            capacity=cap,
            event_id=ev_id,
            is_cuttable=cuttable,
        ))
        return arc_idx

    # Event nodes: for each event e, create e_in and e_out
    event_in_nodes: dict[str, int] = {}
    event_out_nodes: dict[str, int] = {}

    # Sort normalized events canonically by (occurred_at, event_id)
    sorted_events = sorted(normalized, key=lambda ev: (ev.occurred_at, ev.event_id))

    for e in sorted_events:
        if current_node + 2 > cfg.max_expanded_vertices:
            raise BudgetExceededError(
                f"Expanded vertex count exceeds limit ({cfg.max_expanded_vertices})."
            )
        e_in = current_node
        e_out = current_node + 1
        current_node += 2
        event_in_nodes[e.event_id] = e_in
        event_out_nodes[e.event_id] = e_out

        if e.event_id in event_encoded_cost:
            cap = event_encoded_cost[e.event_id]
            is_cut = True
        else:
            cap = inf_capacity
            is_cut = False

        arc_idx = add_arc(e_in, e_out, cap, ev_id=e.event_id, cuttable=is_cut)
        if is_cut:
            event_arc_indices[e.event_id] = arc_idx

    # Group events by account and chronological timestamps
    account_timestamps: dict[str, set[datetime]] = defaultdict(set)
    account_incoming: dict[str, dict[datetime, list[NormalizedEvent]]] = defaultdict(lambda: defaultdict(list))
    account_outgoing: dict[str, dict[datetime, list[NormalizedEvent]]] = defaultdict(lambda: defaultdict(list))

    for e in sorted_events:
        account_timestamps[e.sender_account_id].add(e.occurred_at)
        account_timestamps[e.receiver_account_id].add(e.occurred_at)
        account_outgoing[e.sender_account_id][e.occurred_at].append(e)
        account_incoming[e.receiver_account_id][e.occurred_at].append(e)

    # Timeline nodes per account
    timeline_nodes: dict[tuple[str, datetime], int] = {}

    for acct_id, t_set in account_timestamps.items():
        sorted_times = sorted(t_set)
        m = len(sorted_times)

        for t in sorted_times:
            if current_node + 1 > cfg.max_expanded_vertices:
                raise BudgetExceededError(
                    f"Expanded vertex count exceeds limit ({cfg.max_expanded_vertices})."
                )
            timeline_nodes[(acct_id, t)] = current_node
            current_node += 1

        # Waiting arcs between successive timeline points
        for k in range(m - 1):
            t_curr = sorted_times[k]
            t_next = sorted_times[k + 1]
            from_t_node = timeline_nodes[(acct_id, t_curr)]
            to_t_node = timeline_nodes[(acct_id, t_next)]
            add_arc(from_t_node, to_t_node, inf_capacity)

        # Connect incoming events to timeline nodes: e_out -> (acct, t_k)
        for k, t_k in enumerate(sorted_times):
            in_events = account_incoming[acct_id].get(t_k, [])
            t_node = timeline_nodes[(acct_id, t_k)]
            for in_e in in_events:
                e_out = event_out_nodes[in_e.event_id]
                add_arc(e_out, t_node, inf_capacity)

        # Connect timeline to outgoing events: (acct, t_{k-1}) -> e_in
        # This guarantees next_edge.occurred_at > current_edge.occurred_at strictly
        for k, t_k in enumerate(sorted_times):
            out_events = account_outgoing[acct_id].get(t_k, [])
            if k > 0 and out_events:
                t_prev = sorted_times[k - 1]
                t_prev_node = timeline_nodes[(acct_id, t_prev)]
                for out_e in out_events:
                    e_in = event_in_nodes[out_e.event_id]
                    add_arc(t_prev_node, e_in, inf_capacity)

    # 6. Connect global SOURCE to initial departures from source accounts
    for e in sorted_events:
        if e.sender_account_id in source_set:
            e_in = event_in_nodes[e.event_id]
            add_arc(SOURCE_NODE, e_in, inf_capacity)

    # 7. Connect departures arriving at sink accounts to global SINK
    for e in sorted_events:
        if e.receiver_account_id in sink_set:
            e_out = event_out_nodes[e.event_id]
            add_arc(e_out, SINK_NODE, inf_capacity)

    return TimeExpandedNetwork(
        num_nodes=current_node,
        source_node=SOURCE_NODE,
        sink_node=SINK_NODE,
        arcs=tuple(arcs),
        event_arc_indices=event_arc_indices,
        eligible_event_ids=tuple(e.event_id for e in eligible_events),
        ineligible_event_ids=tuple(e.event_id for e in ineligible_events),
        total_finite_capacity=total_finite_capacity,
        inf_capacity=inf_capacity,
        event_lookup=event_lookup,
        event_collateral=event_collateral,
    )
