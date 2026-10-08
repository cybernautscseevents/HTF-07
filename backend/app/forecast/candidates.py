"""Candidate generation for forecast-aware counterfactual intervention.

Generates intervention candidates visible at time T:
1. Currently tainted accounts (eligible for ACCOUNT_HOLD)
2. Predicted destination/relay accounts appearing across top-K future scenarios
3. Predicted future edge events (eligible for EDGE_HOLD)
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from backend.app.counterfactual.models import (
    InterventionCandidate,
    InterventionType,
)
from backend.app.forecast.generator import ForecastScenario
from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.optimization.models import candidate_sort_key
from backend.app.taint.models import TaintResult


def generate_forecast_candidates(
    graph: TemporalGraph,
    taint_at_t: TaintResult,
    simulation_timestamp: datetime,
    scenarios: Sequence[ForecastScenario] = (),
    include_edge_holds: bool = False,
) -> list[InterventionCandidate]:
    """Generate intervention candidates from currently tainted accounts and predicted paths.

    Parameters
    ----------
    graph : TemporalGraph
        Graph at time T.
    taint_at_t : TaintResult
        Taint state at time T.
    simulation_timestamp : datetime
        Current simulation timestamp.
    scenarios : Sequence[ForecastScenario], optional
        Generated plausible future scenarios.
    include_edge_holds : bool
        Whether to include forecast edge hold candidates.

    Returns
    -------
    list[InterventionCandidate]
        Deduplicated, deterministically ordered list of candidates.
    """
    if simulation_timestamp.tzinfo is None:
        raise ValueError("simulation_timestamp must be timezone-aware.")

    seen_accounts: set[str] = set()
    candidates: list[InterventionCandidate] = []

    # 1. Accounts currently holding tainted balances
    for balance in taint_at_t.current_tainted_accounts():
        if balance.tainted_balance_minor_units > 0:
            acct_id = balance.account_id
            if acct_id not in seen_accounts:
                seen_accounts.add(acct_id)
                candidates.append(
                    InterventionCandidate(
                        intervention_type=InterventionType.ACCOUNT_HOLD,
                        target_account_id=acct_id,
                    )
                )

    # 2. Predicted relay and destination accounts across plausible futures
    for scenario in scenarios:
        for hop in scenario.path.hops:
            for acct_id in (hop.from_account_id, hop.to_account_id):
                if acct_id not in seen_accounts:
                    seen_accounts.add(acct_id)
                    candidates.append(
                        InterventionCandidate(
                            intervention_type=InterventionType.ACCOUNT_HOLD,
                            target_account_id=acct_id,
                        )
                    )

        # 3. Optional edge holds on forecast edges
        if include_edge_holds:
            for fc_evt in scenario.forecast_events:
                candidates.append(
                    InterventionCandidate(
                        intervention_type=InterventionType.EDGE_HOLD,
                        target_event_id=fc_evt.event_id,
                    )
                )

    candidates.sort(key=candidate_sort_key)
    return candidates
