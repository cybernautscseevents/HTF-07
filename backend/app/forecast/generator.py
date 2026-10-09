"""Deterministic future path and scenario generator for forecast-aware simulation.

Guarantees:
-----------
1. Strict Temporal Causality:
   - Evaluates only graph state and features available at or before simulation_timestamp.
   - All forecast events have occurred_at > simulation_timestamp.
2. Bounded Search via Deterministic Beam Search:
   - Configurable top_k beam width and max_depth horizon.
   - Stable tie-breaking without random sampling.
   - Cycle prevention: paths do not revisit accounts already traversed.
3. Explicit Amount Modeling:
   - Models 100% forwardable tainted balance along the path, bounded by available
     modeled balance in integer minor units (paise).
4. Simulation-Only Future Worlds:
   - Forecast events are strictly ephemeral and injected into temporary in-memory
     graphs for CounterfactualSimulator evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
from typing import Sequence

from backend.app.forecast.models import (
    ForecastHop,
    ForecastPath,
    ForecastTransactionEvent,
)
from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.ml.next_hop import NextHopPredictor, get_upstream_ancestors
from backend.app.taint.engine import TaintEngine
from backend.app.taint.models import TaintResult, TaintSeed
from contracts.account import AccountReference
from contracts.transaction import TransactionEvent


@dataclass(frozen=True, slots=True)
class ForecastScenario:
    """A plausible future world combining observed history and a forecast path."""

    scenario_id: str
    path: ForecastPath
    cumulative_probability: float
    normalized_weight: float
    forecast_events: tuple[ForecastTransactionEvent, ...]
    graph: TemporalGraph
    baseline_taint: TaintResult


@dataclass(frozen=True, slots=True)
class ForecastGeneratorConfig:
    """Configuration for bounded future trajectory generation."""

    top_k: int = 3
    max_depth: int = 3
    hop_delay_seconds: float = 300.0
    min_probability: float = 0.01
    currency: str = "INR"

    def __post_init__(self) -> None:
        if self.top_k < 1:
            raise ValueError("top_k must be at least 1.")
        if self.max_depth < 1:
            raise ValueError("max_depth must be at least 1.")
        if self.hop_delay_seconds <= 0:
            raise ValueError("hop_delay_seconds must be positive.")
        if not (0.0 <= self.min_probability <= 1.0):
            raise ValueError("min_probability must be between 0.0 and 1.0.")


def _path_id(source_account_id: str, sequence: Sequence[str], sim_time: datetime) -> str:
    """Deterministic path identifier derived from accounts and timestamp."""
    raw = f"{source_account_id}:{'->'.join(sequence)}:{sim_time.isoformat()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"path-{digest}"


def _event_id(path_id: str, hop_index: int, from_acct: str, to_acct: str) -> str:
    """Deterministic forecast event ID."""
    raw = f"{path_id}:{hop_index}:{from_acct}:{to_acct}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"fc-evt-{path_id[:8]}-h{hop_index:02d}-{digest}"


class ForecastPathGenerator:
    """Generates bounded plausible future trajectories from current graph state."""

    def __init__(
        self,
        predictor: NextHopPredictor | None = None,
        config: ForecastGeneratorConfig | None = None,
    ) -> None:
        self.predictor = predictor or NextHopPredictor()
        self.config = config or ForecastGeneratorConfig()

    def generate_paths(
        self,
        graph: TemporalGraph,
        active_sources: dict[str, int],
        simulation_timestamp: datetime,
        candidate_pool: Sequence[str] | None = None,
        institution_map: dict[str, str] | None = None,
    ) -> tuple[ForecastPath, ...]:
        """Generate top-K plausible future paths using deterministic beam search.

        Parameters
        ----------
        graph : TemporalGraph
            Temporal graph containing historical events (only events <= simulation_timestamp
            are queried).
        active_sources : dict[str, int]
            Mapping of account_id -> current modeled forwardable tainted balance (minor units).
        simulation_timestamp : datetime
            Strict temporal boundary. No real event after this time is examined.
        candidate_pool : Sequence[str], optional
            Pool of candidate destination accounts.
        institution_map : dict[str, str], optional
            Account-to-institution mapping for ML feature extraction.

        Returns
        -------
        tuple[ForecastPath, ...]
            Deterministically ordered tuple of plausible paths.
        """
        if simulation_timestamp.tzinfo is None:
            raise ValueError("simulation_timestamp must be timezone-aware.")

        # Filter sources with positive forwardable balance
        eligible_sources = sorted(
            [acc for acc, bal in active_sources.items() if bal > 0]
        )
        if not eligible_sources:
            return ()

        all_completed_paths: list[ForecastPath] = []

        for source_id in eligible_sources:
            amount = active_sources[source_id]
            source_paths = self._beam_search_source(
                graph=graph,
                source_id=source_id,
                amount=amount,
                simulation_timestamp=simulation_timestamp,
                candidate_pool=candidate_pool,
                institution_map=institution_map,
            )
            all_completed_paths.extend(source_paths)

        # Sort all paths deterministically by:
        # 1. Descending cumulative probability
        # 2. Ascending hop count
        # 3. Deterministic accounts sequence
        all_completed_paths.sort(
            key=lambda p: (
                -p.cumulative_probability,
                len(p.hops),
                p.accounts_sequence,
            )
        )

        # Deduplicate paths (ensures no duplicate sequences across sources)
        seen_sequences: set[tuple[str, ...]] = set()
        deduped: list[ForecastPath] = []
        for path in all_completed_paths:
            seq = path.accounts_sequence
            if seq not in seen_sequences:
                seen_sequences.add(seq)
                deduped.append(path)

        # Retain at most config.top_k paths
        return tuple(deduped[: self.config.top_k])

    def _beam_search_source(
        self,
        graph: TemporalGraph,
        source_id: str,
        amount: int,
        simulation_timestamp: datetime,
        candidate_pool: Sequence[str] | None,
        institution_map: dict[str, str] | None,
    ) -> list[ForecastPath]:
        """Run beam search starting from a single source account."""
        # Initial beam with empty hops
        # Beam entry: (current_account, cumulative_probability, hops, visited_set)
        # Avoid revisiting prior accounts in the historical flow leading into source_id
        upstream_ancestors = get_upstream_ancestors(graph, source_id, simulation_timestamp)
        initial_visited = {source_id} | upstream_ancestors
        current_beam: list[tuple[str, float, list[ForecastHop], set[str]]] = [
            (source_id, 1.0, [], initial_visited)
        ]

        completed_paths: list[ForecastPath] = []

        for depth in range(1, self.config.max_depth + 1):
            next_candidates: list[tuple[str, float, list[ForecastHop], set[str]]] = []

            for current_node, cum_prob, hops, visited in current_beam:
                hop_time = simulation_timestamp + timedelta(
                    seconds=self.config.hop_delay_seconds * depth
                )

                # Query next-hop prediction up to simulation_timestamp
                prediction = self.predictor.predict_next_hop(
                    graph=graph,
                    source_account_id=current_node,
                    as_of_time=simulation_timestamp,
                    candidate_pool=candidate_pool,
                    institution_map=institution_map,
                    top_k=self.config.top_k * 2,  # query enough to allow filtering visited
                )

                # Filter valid candidates (no self-loops, no previously visited nodes)
                valid_candidates = [
                    c for c in prediction.candidates
                    if c.account_id not in visited
                    and c.predicted_probability >= self.config.min_probability
                ]

                # Stable tie-breaking: sort by (-probability, account_id)
                valid_candidates.sort(
                    key=lambda c: (-c.predicted_probability, c.account_id)
                )

                if not valid_candidates:
                    # No further expansion possible: finalize path if it has at least 1 hop
                    if hops:
                        seq = (source_id,) + tuple(h.to_account_id for h in hops)
                        pid = _path_id(source_id, seq, simulation_timestamp)
                        completed_paths.append(
                            ForecastPath(
                                path_id=pid,
                                source_account_id=source_id,
                                hops=tuple(hops),
                                cumulative_probability=cum_prob,
                                accounts_sequence=seq,
                            )
                        )
                    continue

                for cand in valid_candidates[: self.config.top_k]:
                    cand_prob = cand.predicted_probability
                    new_cum_prob = cum_prob * cand_prob
                    new_hop = ForecastHop(
                        from_account_id=current_node,
                        to_account_id=cand.account_id,
                        amount_minor_units=amount,
                        probability=cand_prob,
                        occurred_at=hop_time,
                        candidate_signals=dict(cand.candidate_signals),
                    )
                    new_hops = hops + [new_hop]
                    new_visited = visited | {cand.account_id}
                    next_candidates.append(
                        (cand.account_id, new_cum_prob, new_hops, new_visited)
                    )

            if not next_candidates:
                break

            # Sort next_candidates deterministically:
            # (-new_cum_prob, tuple of destination account IDs)
            next_candidates.sort(
                key=lambda item: (
                    -item[1],
                    tuple(h.to_account_id for h in item[2]),
                )
            )

            # Keep top-K in beam
            current_beam = next_candidates[: self.config.top_k]

            # If reaching max_depth, convert all current beam entries to completed paths
            if depth == self.config.max_depth:
                for _, final_cum_prob, final_hops, _ in current_beam:
                    seq = (source_id,) + tuple(h.to_account_id for h in final_hops)
                    pid = _path_id(source_id, seq, simulation_timestamp)
                    completed_paths.append(
                        ForecastPath(
                            path_id=pid,
                            source_account_id=source_id,
                            hops=tuple(final_hops),
                            cumulative_probability=final_cum_prob,
                            accounts_sequence=seq,
                        )
                    )

        return completed_paths

    def build_future_scenarios(
        self,
        historical_graph: TemporalGraph,
        paths: Sequence[ForecastPath],
        taint_seeds: Sequence[TaintSeed],
        simulation_timestamp: datetime,
    ) -> tuple[ForecastScenario, ...]:
        """Construct isolated simulation-only future worlds for each forecast path.

        For each path:
        1. Ingest historical events <= simulation_timestamp into a fresh TemporalGraph.
        2. Construct ForecastTransactionEvent instances for each hop (occurred_at > T).
        3. Ingest forecast events into the graph as active flows.
        4. Replay TaintEngine to establish baseline taint state for this future world.
        """
        if not paths:
            return ()

        # Extract all historical events up to simulation_timestamp
        historical_edges = historical_graph.events_between(
            end=simulation_timestamp, active_only=True
        )

        total_prob = sum(p.cumulative_probability for p in paths)
        scenarios: list[ForecastScenario] = []

        for idx, path in enumerate(paths, start=1):
            weight = (
                path.cumulative_probability / total_prob
                if total_prob > 0
                else 1.0 / len(paths)
            )

            scenario_id = f"future-world-{idx:02d}-{path.path_id[:8]}"

            # Build in-memory future graph
            future_graph = TemporalGraph()
            for edge in historical_edges:
                future_graph.add_event(
                    TransactionEvent(
                        event_id=edge.event_id,
                        transaction_id=edge.transaction_id,
                        sender=AccountReference(account_id=edge.sender_id),
                        receiver=AccountReference(account_id=edge.receiver_id),
                        amount_minor_units=edge.amount_minor_units,
                        currency=edge.currency,
                        occurred_at=edge.occurred_at,
                        observed_at=edge.observed_at,
                        status=edge.status,
                        channel=edge.channel,
                        origin=edge.origin,
                    )
                )

            # Generate forecast transaction events
            fc_events: list[ForecastTransactionEvent] = []
            for hop_idx, hop in enumerate(path.hops, start=1):
                fc_evt = ForecastTransactionEvent(
                    event_id=_event_id(path.path_id, hop_idx, hop.from_account_id, hop.to_account_id),
                    transaction_id=f"fc-txn-{path.path_id[:8]}-h{hop_idx:02d}",
                    sender_account_id=hop.from_account_id,
                    receiver_account_id=hop.to_account_id,
                    amount_minor_units=hop.amount_minor_units,
                    currency=self.config.currency,
                    occurred_at=hop.occurred_at,
                    probability=hop.probability,
                    path_id=path.path_id,
                    hop_index=hop_idx,
                )
                fc_events.append(fc_evt)
                # Add to simulation graph
                future_graph.add_event(fc_evt.to_simulation_event())

            # Run TaintEngine to establish baseline taint in this future world
            baseline_taint = TaintEngine().run(future_graph, list(taint_seeds))

            scenarios.append(
                ForecastScenario(
                    scenario_id=scenario_id,
                    path=path,
                    cumulative_probability=path.cumulative_probability,
                    normalized_weight=weight,
                    forecast_events=tuple(fc_events),
                    graph=future_graph,
                    baseline_taint=baseline_taint,
                )
            )

        return tuple(scenarios)
