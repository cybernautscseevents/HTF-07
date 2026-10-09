"""Deterministic benchmark for the Temporal Chokepoint Search subsystem.

Evaluates the capacity-aware temporal min-cut search against synthetic topologies
with explicitly configured sources and sinks (kept separate from ScenarioTruth).

Reports comparative metrics against a simple heuristic baseline:
- Highest-Taint Eligible Edge baseline

Measurements only; does not claim proprietary superiority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.chokepoint import (
    ChokepointSearchConfig,
    ChokepointStatus,
    find_temporal_chokepoint,
)
from backend.app.counterfactual.models import InterventionCandidate, InterventionType
from backend.app.counterfactual.simulator import CounterfactualSimulator
from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.graph.traversal import find_temporal_paths
from backend.app.optimization.models import OptimizationConstraints
from backend.app.optimization.optimizer import (
    MultiObjectiveInterventionOptimizer,
    ObservedFutureCounterfactualEvaluator,
)
from backend.app.taint.engine import TaintEngine
from backend.app.taint.models import TaintSeed
from contracts.transaction import TransactionEvent
from scripts.generator.scenarios import (
    generate_fan_out_fan_in_scenario,
    generate_simple_chain_scenario,
)

UTC = timezone.utc


def run_highest_taint_baseline(
    graph: TemporalGraph,
    taint_allocations: Sequence[Any],
    simulation_timestamp: datetime,
    eligible_event_ids: set[str],
) -> str | None:
    """Baseline heuristic: Select the single eligible future edge carrying the highest tainted amount."""
    best_event_id: str | None = None
    max_taint = -1

    for alloc in taint_allocations:
        if alloc.event_id in eligible_event_ids and alloc.occurred_at > simulation_timestamp:
            if alloc.tainted_amount_minor_units > max_taint:
                max_taint = alloc.tainted_amount_minor_units
                best_event_id = alloc.event_id

    return best_event_id


def evaluate_scenario_chokepoint(
    scenario_name: str,
    transactions: list[TransactionEvent],
    seed_tx_id: str,
    source_accounts: list[str],
    sink_accounts: list[str],
    case_id: str,
) -> None:
    print(f"\n=======================================================")
    print(f" Scenario: {scenario_name}")
    print(f"=======================================================")

    graph = TemporalGraph()
    graph.build_case(transactions)

    seed_tx = next(tx for tx in transactions if tx.transaction_id == seed_tx_id)
    sim_time = seed_tx.occurred_at

    # Run authoritative taint engine
    taint_result = TaintEngine().run(
        graph,
        [
            TaintSeed(
                case_id=case_id,
                transaction_id=seed_tx.transaction_id,
                tainted_amount_minor_units=seed_tx.amount_minor_units,
            )
        ],
    )

    # Simulator for collateral estimation
    simulator = CounterfactualSimulator(graph, taint_result)

    from contracts.enums import TransactionStatus

    # Determine eligible future events
    eligible_events = {
        tx.event_id for tx in transactions
        if tx.occurred_at > sim_time and tx.status == TransactionStatus.COMPLETED
    }

    # Count paths before cut
    initial_paths = 0
    for s in source_accounts:
        for t in sink_accounts:
            initial_paths += len(find_temporal_paths(graph, s, t, start_time=None))

    # 1. Run Temporal Chokepoint Search
    started = perf_counter()
    search_result = find_temporal_chokepoint(
        graph=graph,
        source_account_ids=source_accounts,
        sink_account_ids=sink_accounts,
        simulation_timestamp=sim_time,
        eligible_event_ids=eligible_events,
        simulator=simulator,
    )
    elapsed_ms = (perf_counter() - started) * 1000.0

    # Policy evaluation for individual feasibility
    optimizer = MultiObjectiveInterventionOptimizer(
        ObservedFutureCounterfactualEvaluator(simulator)
    )
    policy_output = optimizer.optimize(
        candidates=search_result.candidates,
        simulation_timestamp=sim_time,
        constraints=OptimizationConstraints(minimum_required_illicit_recovery=0),
    )
    feasible_count = len(policy_output.feasible_evaluations)

    print(f"source_count={len(source_accounts)}")
    print(f"sink_count={len(sink_accounts)}")
    print(f"candidate_event_count={len(eligible_events)}")
    print(f"status={search_result.status.value}")
    print(f"chokepoint_cut_size={search_result.cut_size}")
    print(f"encoded_total_cut_cost={search_result.total_encoded_cut_cost}")
    print(f"total_estimated_collateral_minor_units={search_result.total_estimated_legitimate_collateral_minor_units}")
    print("per_cut_member_collateral=" + str([
        (e.event_id, e.estimated_legitimate_collateral_minor_units)
        for e in search_result.cut_edges
    ]))
    print(f"paths_before_cut={initial_paths}")
    print(f"paths_after_cut={search_result.diagnostics.residual_path_count}")
    print(f"all_paths_disconnected_verified={search_result.is_cut_verified}")
    print(f"individually_feasible_cut_members={feasible_count}")
    print(f"chokepoint_search_runtime_ms={elapsed_ms:.3f}")

    # 2. Baseline comparison: Highest-Taint Eligible Edge
    baseline_edge_id = run_highest_taint_baseline(
        graph=graph,
        taint_allocations=taint_result.allocations,
        simulation_timestamp=sim_time,
        eligible_event_ids=eligible_events,
    )

    baseline_residual_paths = 0
    if baseline_edge_id is not None:
        filtered_graph = TemporalGraph()
        for edge_data in graph.events_between(active_only=True):
            if edge_data.event_id != baseline_edge_id:
                filtered_graph.add_event(
                    next(tx for tx in transactions if tx.event_id == edge_data.event_id)
                )
        for s in source_accounts:
            for t in sink_accounts:
                baseline_residual_paths += len(find_temporal_paths(filtered_graph, s, t, start_time=None))

    print(f"\n--- Baseline Comparison (Highest-Taint Single Edge) ---")
    print(f"baseline_selected_edge={baseline_edge_id}")
    print(f"baseline_residual_paths_remaining={baseline_residual_paths}")
    print(f"baseline_fully_disconnects_paths={baseline_residual_paths == 0}")
    if baseline_edge_id is not None:
        baseline_cand = InterventionCandidate(
            intervention_type=InterventionType.EDGE_HOLD,
            target_event_id=baseline_edge_id,
        )
        baseline_cf = simulator.simulate(baseline_cand, sim_time)
        print(f"baseline_legitimate_collateral_minor_units={baseline_cf.modeled_legitimate_capital_affected}")
        print(f"tradeoff_analysis: The capacity-aware min-cut incurs {search_result.total_estimated_legitimate_collateral_minor_units} collateral vs baseline's {baseline_cf.modeled_legitimate_capital_affected} collateral.")


def main() -> None:
    print("AEGIS-Flow Temporal Chokepoint Search Benchmark")

    # Benchmark 1: Diamond Topology (Fan-Out Fan-In)
    sc_diamond = generate_fan_out_fan_in_scenario(seed=42)
    # Configure explicit sources and sinks from transaction roles (distinct from ScenarioTruth)
    seed_tx = sc_diamond.transactions[0]
    layer1_acct = seed_tx.receiver.account_id
    exit_acct = next(
        tx.receiver.account_id for tx in reversed(sc_diamond.transactions)
        if "exit" in tx.event_id
    )

    evaluate_scenario_chokepoint(
        scenario_name="Fan-Out Fan-In (Diamond Reconvergence)",
        transactions=sc_diamond.transactions,
        seed_tx_id=seed_tx.transaction_id,
        source_accounts=[layer1_acct],
        sink_accounts=[exit_acct],
        case_id="case-bench-diamond",
    )

    # Benchmark 2: Simple Linear Chain
    sc_chain = generate_simple_chain_scenario(seed=42)
    seed_chain_tx = sc_chain.transactions[0]
    chain_src = seed_chain_tx.receiver.account_id
    chain_sink = next(acc.account_id for acc in sc_chain.accounts if acc.label == "Cashout Account")

    evaluate_scenario_chokepoint(
        scenario_name="Simple Chain (Linear Multi-Hop)",
        transactions=sc_chain.transactions,
        seed_tx_id=seed_chain_tx.transaction_id,
        source_accounts=[chain_src],
        sink_accounts=[chain_sink],
        case_id="case-bench-chain",
    )


if __name__ == "__main__":
    main()
