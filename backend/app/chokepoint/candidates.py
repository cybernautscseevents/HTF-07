"""Chokepoint search orchestrator and intervention candidate generation.

Integrates temporal network construction, Dinic min-cut extraction,
and counterfactual candidate derivation for the AEGIS-Flow architecture.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from decimal import Decimal
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from backend.app.counterfactual.models import (
    InterventionCandidate,
    InterventionType,
)
from backend.app.counterfactual.simulator import CounterfactualSimulator
from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.graph.traversal import find_temporal_paths
from backend.app.optimization.models import (
    OptimizationConstraints,
    OptimizationResult,
)
from backend.app.optimization.optimizer import (
    MultiObjectiveInterventionOptimizer,
    ObservedFutureCounterfactualEvaluator,
)
from backend.app.chokepoint.min_cut import (
    DinicSolver,
    compute_temporal_min_cut,
)
from backend.app.chokepoint.models import (
    ChokepointDiagnostics,
    ChokepointExplanation,
    ChokepointSearchConfig,
    ChokepointSearchResult,
    ChokepointStatus,
    TemporalCutEdge,
)
from backend.app.chokepoint.temporal_network import (
    BudgetExceededError,
    TimeExpandedNetwork,
    build_time_expanded_network,
    extract_normalized_event,
)


class TemporalChokepointSearcher:
    """Orchestrates temporal minimum-cut chokepoint identification and audit."""

    def __init__(self, config: ChokepointSearchConfig | None = None) -> None:
        self._config = config or ChokepointSearchConfig()

    def search(
        self,
        *,
        source_account_ids: Sequence[str],
        sink_account_ids: Sequence[str],
        graph: TemporalGraph | None = None,
        events: Sequence[Any] | None = None,
        simulation_timestamp: datetime | None = None,
        eligible_event_ids: Sequence[str] | set[str] | None = None,
        simulator: CounterfactualSimulator | None = None,
        collateral_lookup: Mapping[str, int] | Callable[[str], int] | None = None,
        config: ChokepointSearchConfig | None = None,
    ) -> ChokepointSearchResult:
        """Find a minimum-cost temporal cut disconnecting sources from sinks."""
        cfg = config or self._config
        start_time = perf_counter()

        sources = tuple(str(s).strip() for s in source_account_ids if str(s).strip())
        sinks = tuple(str(d).strip() for d in sink_account_ids if str(d).strip())

        # Validate basic inputs
        if not sources or not sinks or (set(sources) & set(sinks)):
            elapsed = (perf_counter() - start_time) * 1000.0
            overlap = set(sources) & set(sinks)
            reason = "Source and sink overlap" if overlap else "Missing source or sink accounts"
            return ChokepointSearchResult(
                status=ChokepointStatus.INVALID_INPUT,
                source_account_ids=sources,
                sink_account_ids=sinks,
                cut_edges=(),
                cut_size=0,
                total_encoded_cut_cost=0,
                total_estimated_legitimate_collateral_minor_units=0,
                is_cut_verified=False,
                explanation=ChokepointExplanation(
                    summary=f"Invalid search inputs: {reason}.",
                    sources_analyzed=sources,
                    sinks_targeted=sinks,
                    cut_edge_ids=(),
                    cost_minimality_rationale="No search performed due to invalid input specification.",
                    per_edge_collateral=(),
                    complete_cut_disconnects_all_paths=False,
                    limitations=(),
                ),
                diagnostics=ChokepointDiagnostics(
                    input_active_event_count=0,
                    eligible_cuttable_edge_count=0,
                    expanded_vertex_count=0,
                    expanded_arc_count=0,
                    initial_path_count=0,
                    residual_path_count=0,
                    runtime_ms=elapsed,
                    pruning_reasons=(reason,),
                ),
                candidates=(),
            )

        # Collect events
        if events is not None:
            all_events = list(events)
        elif graph is not None:
            all_events = graph.events_between(active_only=True)
        else:
            all_events = []

        # If simulator is provided and collateral_lookup is not, compute collateral via simulation
        resolved_collateral: dict[str, int] = {}
        if collateral_lookup is not None:
            if callable(collateral_lookup):
                # Will evaluate lazily or pass through
                collateral_provider = collateral_lookup
            else:
                resolved_collateral = dict(collateral_lookup)
                collateral_provider = resolved_collateral
        elif simulator is not None and simulation_timestamp is not None:
            # Pre-evaluate collateral using CounterfactualSimulator for eligible events
            for ev in all_events:
                norm_ev = extract_normalized_event(ev)
                is_elig = (
                    norm_ev.event_id in eligible_event_ids
                    if eligible_event_ids is not None
                    else norm_ev.occurred_at > simulation_timestamp
                )
                if is_elig and norm_ev.is_active:
                    cand = InterventionCandidate(
                        intervention_type=InterventionType.EDGE_HOLD,
                        target_event_id=norm_ev.event_id,
                    )
                    cf_res = simulator.simulate(cand, simulation_timestamp)
                    resolved_collateral[norm_ev.event_id] = cf_res.modeled_legitimate_capital_affected
            collateral_provider = resolved_collateral
        else:
            collateral_provider = resolved_collateral

        # Build network with budget guard
        try:
            network = build_time_expanded_network(
                events=all_events,
                source_account_ids=sources,
                sink_account_ids=sinks,
                simulation_timestamp=simulation_timestamp,
                eligible_event_ids=eligible_event_ids,
                collateral_lookup=collateral_provider,
                config=cfg,
            )
        except BudgetExceededError as err:
            elapsed = (perf_counter() - start_time) * 1000.0
            return ChokepointSearchResult(
                status=ChokepointStatus.BUDGET_EXCEEDED,
                source_account_ids=sources,
                sink_account_ids=sinks,
                cut_edges=(),
                cut_size=0,
                total_encoded_cut_cost=0,
                total_estimated_legitimate_collateral_minor_units=0,
                is_cut_verified=False,
                explanation=ChokepointExplanation(
                    summary=f"Search aborted: {err}",
                    sources_analyzed=sources,
                    sinks_targeted=sinks,
                    cut_edge_ids=(),
                    cost_minimality_rationale="Search halted due to bounded resource limits.",
                    per_edge_collateral=(),
                    complete_cut_disconnects_all_paths=False,
                    limitations=(),
                ),
                diagnostics=ChokepointDiagnostics(
                    input_active_event_count=len(all_events),
                    eligible_cuttable_edge_count=0,
                    expanded_vertex_count=0,
                    expanded_arc_count=0,
                    initial_path_count=0,
                    residual_path_count=0,
                    runtime_ms=elapsed,
                    pruning_reasons=(str(err),),
                ),
                candidates=(),
            )

        # Solve minimum cut
        status, cut_edges, total_encoded_cost, total_collateral = compute_temporal_min_cut(network)

        # Path Verification
        initial_paths_count = 0
        residual_paths_count = 0
        is_verified = False

        if status == ChokepointStatus.NO_PATH_EXISTS:
            initial_paths_count = 0
            residual_paths_count = 0
            is_verified = True
        elif status == ChokepointStatus.OPTIMAL_CUT_FOUND:
            cut_ids_set = {edge.event_id for edge in cut_edges}

            # 1. Residual reachability test in the time-expanded network
            test_solver = DinicSolver(
                num_nodes=network.num_nodes,
                source=network.source_node,
                sink=network.sink_node,
            )
            for arc in network.arcs:
                # If arc corresponds to a cut edge, its capacity becomes 0 (blocked)
                cap = 0 if arc.event_id in cut_ids_set else arc.capacity
                test_solver.add_edge(arc.from_node, arc.to_node, cap, arc_id=arc.arc_id)

            reachable_in_cut = test_solver.get_source_reachable_set()
            residual_network_disconnected = (network.sink_node not in reachable_in_cut)

            # 2. Traversal verification on TemporalGraph if available
            residual_graph_disconnected = True
            if graph is not None:
                # Count paths in graph before cut
                for s in sources:
                    for t in sinks:
                        paths = find_temporal_paths(
                            graph,
                            s,
                            t,
                            start_time=None,
                            max_depth=10,
                        )
                        initial_paths_count += len(paths)
                        if initial_paths_count >= cfg.max_paths_to_verify:
                            break
                    if initial_paths_count >= cfg.max_paths_to_verify:
                        break

                # Count paths after removing cut edges
                filtered_graph = TemporalGraph()
                for e_data in graph.events_between(active_only=True):
                    if e_data.event_id not in cut_ids_set:
                        # Re-ingest
                        filtered_graph._get_or_create_node(e_data.sender_id)
                        filtered_graph._get_or_create_node(e_data.receiver_id)
                        # Re-add as edge
                        filtered_graph._graph.add_edge(
                            filtered_graph._account_to_node[e_data.sender_id],
                            filtered_graph._account_to_node[e_data.receiver_id],
                            e_data,
                        )
                        filtered_graph._event_to_edge[e_data.event_id] = len(filtered_graph._event_to_edge)
                        filtered_graph._index.add(filtered_graph._event_to_edge[e_data.event_id], e_data)

                for s in sources:
                    for t in sinks:
                        rem_paths = find_temporal_paths(
                            filtered_graph,
                            s,
                            t,
                            start_time=None,
                            max_depth=10,
                        )
                        residual_paths_count += len(rem_paths)
                residual_graph_disconnected = (residual_paths_count == 0)

            is_verified = residual_network_disconnected and residual_graph_disconnected

        # Generate candidates from cut edges
        candidates = tuple(edge.to_candidate() for edge in cut_edges)

        # Formulate structured deterministic explanation
        limitations = (
            "Single-edge evaluation constraint: The downstream optimizer evaluates individual "
            "interventions. Executing a multi-edge cut bundle requires multi-intervention planner support.",
            "Additive cost approximation: Encoded cut cost sums individual counterfactual collateral estimates. "
            "Joint interaction effects between simultaneous holds may cause combined collateral to differ from the linear sum.",
            "Temporal observation window: The analysis covers transactions within the modeled time horizon; "
            "future unobserved or unpredicted transactions outside this horizon are not constrained.",
            "Settlement ordering abstraction: Events occurring at identical timestamps are treated as causally "
            "disconnected under the MVP causality rule.",
        )

        rationale = (
            f"Dinic's algorithm evaluated {len(network.eligible_event_ids)} eligible cuttable edges using "
            f"lexicographic integer encoding cost = collateral * (N + 1) + 1. Total legitimate collateral is "
            f"the primary minimization objective, with edge count as the secondary tie-breaker. "
            f"The cut achieves a minimal encoded cost of {total_encoded_cost} with an estimated total legitimate "
            f"collateral disruption of {total_collateral} paise."
        ) if status == ChokepointStatus.OPTIMAL_CUT_FOUND else (
            "No cut found: either no valid temporal path exists or all connecting paths require cutting ineligible edges."
        )

        summary = (
            f"Identified optimal temporal chokepoint consisting of {len(cut_edges)} edge(s) "
            f"separating {len(sources)} source(s) from {len(sinks)} sink(s) with estimated "
            f"collateral disruption of {total_collateral} paise."
        ) if status == ChokepointStatus.OPTIMAL_CUT_FOUND else (
            f"Chokepoint search completed with status: {status.value}."
        )

        explanation = ChokepointExplanation(
            summary=summary,
            sources_analyzed=sources,
            sinks_targeted=sinks,
            cut_edge_ids=tuple(e.event_id for e in cut_edges),
            cost_minimality_rationale=rationale,
            per_edge_collateral=tuple(
                (e.event_id, e.estimated_legitimate_collateral_minor_units)
                for e in cut_edges
            ),
            complete_cut_disconnects_all_paths=is_verified,
            limitations=limitations,
        )

        elapsed_ms = (perf_counter() - start_time) * 1000.0

        diagnostics = ChokepointDiagnostics(
            input_active_event_count=len(all_events),
            eligible_cuttable_edge_count=len(network.eligible_event_ids),
            expanded_vertex_count=network.num_nodes,
            expanded_arc_count=len(network.arcs),
            initial_path_count=initial_paths_count,
            residual_path_count=residual_paths_count,
            runtime_ms=elapsed_ms,
            pruning_reasons=(),
        )

        return ChokepointSearchResult(
            status=status,
            source_account_ids=sources,
            sink_account_ids=sinks,
            cut_edges=cut_edges,
            cut_size=len(cut_edges),
            total_encoded_cut_cost=total_encoded_cost,
            total_estimated_legitimate_collateral_minor_units=total_collateral,
            is_cut_verified=is_verified,
            explanation=explanation,
            diagnostics=diagnostics,
            candidates=candidates,
        )


def find_temporal_chokepoint(
    source_account_ids: Sequence[str],
    sink_account_ids: Sequence[str],
    graph: TemporalGraph | None = None,
    events: Sequence[Any] | None = None,
    simulation_timestamp: datetime | None = None,
    eligible_event_ids: Sequence[str] | set[str] | None = None,
    simulator: CounterfactualSimulator | None = None,
    collateral_lookup: Mapping[str, int] | Callable[[str], int] | None = None,
    config: ChokepointSearchConfig | None = None,
) -> ChokepointSearchResult:
    """Convenience functional wrapper for TemporalChokepointSearcher.search."""
    searcher = TemporalChokepointSearcher(config=config)
    return searcher.search(
        source_account_ids=source_account_ids,
        sink_account_ids=sink_account_ids,
        graph=graph,
        events=events,
        simulation_timestamp=simulation_timestamp,
        eligible_event_ids=eligible_event_ids,
        simulator=simulator,
        collateral_lookup=collateral_lookup,
        config=config,
    )


def generate_chokepoint_candidates(
    source_account_ids: Sequence[str],
    sink_account_ids: Sequence[str],
    graph: TemporalGraph | None = None,
    events: Sequence[Any] | None = None,
    simulation_timestamp: datetime | None = None,
    eligible_event_ids: Sequence[str] | set[str] | None = None,
    simulator: CounterfactualSimulator | None = None,
    collateral_lookup: Mapping[str, int] | Callable[[str], int] | None = None,
    config: ChokepointSearchConfig | None = None,
) -> list[InterventionCandidate]:
    """Generate individually evaluable InterventionCandidate instances from chokepoint cut members."""
    res = find_temporal_chokepoint(
        source_account_ids=source_account_ids,
        sink_account_ids=sink_account_ids,
        graph=graph,
        events=events,
        simulation_timestamp=simulation_timestamp,
        eligible_event_ids=eligible_event_ids,
        simulator=simulator,
        collateral_lookup=collateral_lookup,
        config=config,
    )
    return list(res.candidates)


def evaluate_chokepoint_candidates_with_optimizer(
    search_result: ChokepointSearchResult,
    simulator: CounterfactualSimulator,
    simulation_timestamp: datetime,
    constraints: OptimizationConstraints | None = None,
) -> OptimizationResult:
    """Evaluate individual chokepoint cut members with MultiObjectiveInterventionOptimizer."""
    optimizer = MultiObjectiveInterventionOptimizer(
        evaluator=ObservedFutureCounterfactualEvaluator(simulator)
    )
    return optimizer.optimize(
        candidates=search_result.candidates,
        simulation_timestamp=simulation_timestamp,
        constraints=constraints,
    )
