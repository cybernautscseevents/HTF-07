"""
Structural motif detection in the temporal financial flow graph.

Motifs are small, recurring sub-graph patterns that are common in
layering, structuring, and mule-network fraud typologies.

All detectors operate on **active-flow edges only** (``completed``).

Detected motifs
---------------
* **Fan-out** — one account sends to N+ distinct accounts in a window.
* **Fan-in** — one account receives from N+ distinct accounts in a window.
* **Rapid pass-through** — an account receives then sends within a short
  time delta (possible mule behaviour).
* **Fan-out → Fan-in** — compound pattern where a source fans out to
  intermediaries that converge on a single target.

Complexity notes
----------------
* Fan-out / fan-in: O(A · E_a²) where A is account count and E_a is
  the max active edge count per account.  Bounded in practice by sparse
  real-world graphs.
* Rapid pass-through: O(A · (I_a + O_a)) amortized per account — the
  two-pointer scan advances monotonically over both sorted lists.
* Fan-out-fan-in: depends on fan-out result count × intermediary edges.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from backend.app.graph.temporal_index import EdgeData

if TYPE_CHECKING:
    from backend.app.graph.temporal_graph import TemporalGraph


# ── Result dataclasses ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FanOutMotif:
    """A single account sending to multiple distinct targets in a window."""

    source: str
    targets: frozenset[str]
    edges: tuple[EdgeData, ...]
    window_start: datetime
    window_end: datetime


@dataclass(frozen=True, slots=True)
class FanInMotif:
    """Multiple distinct sources sending to a single account in a window."""

    target: str
    sources: frozenset[str]
    edges: tuple[EdgeData, ...]
    window_start: datetime
    window_end: datetime


@dataclass(frozen=True, slots=True)
class PassThroughMotif:
    """An account that receives and then rapidly forwards funds."""

    account: str
    incoming_edge: EdgeData
    outgoing_edge: EdgeData
    delay_seconds: float


@dataclass(frozen=True, slots=True)
class FanOutFanInMotif:
    """Source fans out to intermediaries that converge on a target."""

    source: str
    target: str
    intermediaries: frozenset[str]
    fan_out_edges: tuple[EdgeData, ...]
    fan_in_edges: tuple[EdgeData, ...]


# ── Detection algorithms ─────────────────────────────────────────────────────


def detect_fan_out(
    graph: TemporalGraph,
    window_seconds: float = 3600.0,
    min_targets: int = 3,
) -> list[FanOutMotif]:
    """Find accounts that send to ≥ *min_targets* distinct accounts
    within *window_seconds*.

    Returns at most one motif per source account (the first qualifying
    window found).
    """
    results: list[FanOutMotif] = []

    for account_id in graph.accounts:
        outgoing = graph.outgoing(account_id, active_only=True)
        if len(outgoing) < min_targets:
            continue

        found = False
        for i in range(len(outgoing)):
            if found:
                break
            window_end_time = outgoing[i].occurred_at + timedelta(
                seconds=window_seconds,
            )
            targets: set[str] = set()
            window_edges: list[EdgeData] = []

            for j in range(i, len(outgoing)):
                if outgoing[j].occurred_at > window_end_time:
                    break
                targets.add(outgoing[j].receiver_id)
                window_edges.append(outgoing[j])

            if len(targets) >= min_targets:
                results.append(
                    FanOutMotif(
                        source=account_id,
                        targets=frozenset(targets),
                        edges=tuple(window_edges),
                        window_start=outgoing[i].occurred_at,
                        window_end=window_edges[-1].occurred_at,
                    )
                )
                found = True

    return results


def detect_fan_in(
    graph: TemporalGraph,
    window_seconds: float = 3600.0,
    min_sources: int = 3,
) -> list[FanInMotif]:
    """Find accounts that receive from ≥ *min_sources* distinct accounts
    within *window_seconds*.

    Returns at most one motif per target account (the first qualifying
    window found).
    """
    results: list[FanInMotif] = []

    for account_id in graph.accounts:
        incoming = graph.incoming(account_id, active_only=True)
        if len(incoming) < min_sources:
            continue

        found = False
        for i in range(len(incoming)):
            if found:
                break
            window_end_time = incoming[i].occurred_at + timedelta(
                seconds=window_seconds,
            )
            sources: set[str] = set()
            window_edges: list[EdgeData] = []

            for j in range(i, len(incoming)):
                if incoming[j].occurred_at > window_end_time:
                    break
                sources.add(incoming[j].sender_id)
                window_edges.append(incoming[j])

            if len(sources) >= min_sources:
                results.append(
                    FanInMotif(
                        target=account_id,
                        sources=frozenset(sources),
                        edges=tuple(window_edges),
                        window_start=incoming[i].occurred_at,
                        window_end=window_edges[-1].occurred_at,
                    )
                )
                found = True

    return results


def detect_rapid_pass_through(
    graph: TemporalGraph,
    max_delay_seconds: float = 300.0,
) -> list[PassThroughMotif]:
    """Find accounts that receive and then send within *max_delay_seconds*.

    For each account, pairs each active incoming edge with the first
    active outgoing edge that occurs within the delay window.
    """
    results: list[PassThroughMotif] = []

    for account_id in graph.accounts:
        incoming = graph.incoming(account_id, active_only=True)
        outgoing = graph.outgoing(account_id, active_only=True)

        if not incoming or not outgoing:
            continue

        # Both lists are sorted by occurred_at.  Use a pointer to
        # avoid re-scanning outgoing for each incoming edge.
        out_ptr = 0

        for in_edge in incoming:
            # Advance pointer to first outgoing edge at or after in_edge time.
            while (
                out_ptr < len(outgoing)
                and outgoing[out_ptr].occurred_at < in_edge.occurred_at
            ):
                out_ptr += 1

            # Scan outgoing edges within the delay window.
            for k in range(out_ptr, len(outgoing)):
                out_edge = outgoing[k]
                delay = (
                    out_edge.occurred_at - in_edge.occurred_at
                ).total_seconds()
                if delay > max_delay_seconds:
                    break
                if delay >= 0:
                    results.append(
                        PassThroughMotif(
                            account=account_id,
                            incoming_edge=in_edge,
                            outgoing_edge=out_edge,
                            delay_seconds=delay,
                        )
                    )
                    break  # first qualifying pair per incoming edge

    return results


def detect_fan_out_fan_in(
    graph: TemporalGraph,
    window_seconds: float = 3600.0,
    min_intermediaries: int = 3,
) -> list[FanOutFanInMotif]:
    """Detect source → intermediaries → target compound patterns.

    Uses :func:`detect_fan_out` to find fan-out sources, then checks
    whether the intermediary accounts converge on a common downstream
    target.
    """
    fan_outs = detect_fan_out(
        graph, window_seconds=window_seconds, min_targets=min_intermediaries,
    )

    results: list[FanOutFanInMotif] = []

    for fan_out in fan_outs:
        # For each intermediary, collect where they send funds after
        # receiving from the fan-out source.
        target_flows: dict[str, list[tuple[str, EdgeData]]] = defaultdict(list)

        for inter_id in fan_out.targets:
            inter_outgoing = graph.outgoing(
                inter_id, start=fan_out.window_start, active_only=True,
            )
            for edge in inter_outgoing:
                if (
                    edge.occurred_at > fan_out.window_start
                    and edge.receiver_id != fan_out.source
                ):
                    target_flows[edge.receiver_id].append((inter_id, edge))

        # Check if any downstream target received from enough intermediaries.
        for target_id, flows in target_flows.items():
            unique_inters = {inter_id for inter_id, _ in flows}
            if len(unique_inters) >= min_intermediaries:
                results.append(
                    FanOutFanInMotif(
                        source=fan_out.source,
                        target=target_id,
                        intermediaries=frozenset(unique_inters),
                        fan_out_edges=fan_out.edges,
                        fan_in_edges=tuple(e for _, e in flows),
                    )
                )

    return results
