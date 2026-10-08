"""Candidate generation for counterfactual intervention simulation.

This module derives intervention candidates from existing taint state.
Candidate generation is deliberately separated from simulation — it
contains no ML logic and no optimization scoring.

Candidates are generated from:
* Currently tainted downstream accounts (→ ACCOUNT_HOLD candidates)
* Tainted future edges (→ EDGE_HOLD candidates)
"""

from __future__ import annotations

from datetime import datetime

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.taint.models import TaintResult

from backend.app.counterfactual.models import (
    InterventionCandidate,
    InterventionType,
)


def generate_candidates(
    graph: TemporalGraph,
    baseline_result: TaintResult,
    simulation_timestamp: datetime,
) -> list[InterventionCandidate]:
    """Derive intervention candidates from baseline taint state.

    Parameters
    ----------
    graph : TemporalGraph
        The temporal graph (read-only).
    baseline_result : TaintResult
        The baseline taint result (read-only).
    simulation_timestamp : datetime
        The simulation time.  Only future events/accounts are candidates.

    Returns
    -------
    list[InterventionCandidate]
        Deduplicated, deterministically ordered candidate list.
    """
    if simulation_timestamp.tzinfo is None:
        raise ValueError("simulation_timestamp must be timezone-aware.")

    candidates: list[InterventionCandidate] = []
    seen_accounts: set[str] = set()
    seen_events: set[str] = set()

    # Generate ACCOUNT_HOLD candidates from currently tainted accounts
    # that have future outbound activity
    for balance in baseline_result.current_tainted_accounts():
        account_id = balance.account_id
        if account_id in seen_accounts:
            continue

        # Check if this account has any future outbound active edges
        future_out = graph.outgoing(
            account_id, start=simulation_timestamp, active_only=True
        )
        has_future = any(e.occurred_at > simulation_timestamp for e in future_out)
        if has_future:
            seen_accounts.add(account_id)
            candidates.append(
                InterventionCandidate(
                    intervention_type=InterventionType.ACCOUNT_HOLD,
                    target_account_id=account_id,
                )
            )

    # Generate EDGE_HOLD candidates from tainted future edges
    for alloc in baseline_result.allocations:
        if alloc.occurred_at <= simulation_timestamp:
            continue  # historical
        if alloc.tainted_amount_minor_units <= 0:
            continue  # no taint on this edge
        event_id = alloc.event_id
        if event_id in seen_events:
            continue

        seen_events.add(event_id)
        candidates.append(
            InterventionCandidate(
                intervention_type=InterventionType.EDGE_HOLD,
                target_event_id=event_id,
            )
        )

    # Sort deterministically
    candidates.sort(
        key=lambda c: (
            c.intervention_type.value,
            c.target_account_id or "",
            c.target_event_id or "",
        )
    )

    return candidates
