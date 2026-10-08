"""Small deterministic benchmark for the intervention optimizer.

This benchmark reports measured values only; it does not claim superiority
over any baseline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from backend.app.counterfactual.candidates import generate_candidates
from backend.app.counterfactual.simulator import CounterfactualSimulator
from backend.app.optimization import (
    MultiObjectiveInterventionOptimizer,
    ObservedFutureCounterfactualEvaluator,
    OptimizationConstraints,
)
from backend.app.taint.models import TaintSeed
from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.taint.engine import TaintEngine
from scripts.generator.scenarios import generate_simple_chain_scenario


def main() -> None:
    scenario = generate_simple_chain_scenario(seed=42)
    graph = TemporalGraph()
    graph.build_case(scenario.transactions)
    seed_event = next(
        event
        for event in scenario.transactions
        if event.transaction_id in scenario.truth.seed_transaction_ids
    )
    taint = TaintEngine().run(
        graph,
        [
            TaintSeed(
                case_id=scenario.truth.case_id,
                transaction_id=seed_event.transaction_id,
                tainted_amount_minor_units=seed_event.amount_minor_units,
            )
        ],
    )
    simulation_timestamp = seed_event.occurred_at
    candidates = generate_candidates(graph, taint, simulation_timestamp)
    optimizer = MultiObjectiveInterventionOptimizer(
        ObservedFutureCounterfactualEvaluator(CounterfactualSimulator(graph, taint))
    )
    started = perf_counter()
    output = optimizer.optimize(
        candidates,
        simulation_timestamp,
        OptimizationConstraints(),
    )
    elapsed_ms = (perf_counter() - started) * 1000
    selected = output.selected_evaluation
    print(f"total_candidate_count={len(output.evaluations)}")
    print(f"feasible_candidate_count={len(output.feasible_evaluations)}")
    print(f"pareto_frontier_size={output.pareto_frontier.size}")
    print(
        "selected_intervention="
        f"{selected.intervention_id if selected is not None else 'none'}"
    )
    print(
        "illicit_capital_intercepted="
        f"{selected.result.modeled_tainted_capital_intercepted if selected else 0}"
    )
    print(
        "legitimate_capital_affected="
        f"{selected.result.modeled_legitimate_capital_affected if selected else 0}"
    )
    print(
        "recovery_collateral_efficiency="
        f"{selected.recovery_efficiency if selected else 'none'}"
    )
    print(
        "affected_account_count="
        f"{selected.result.number_of_affected_accounts if selected else 0}"
    )
    print(
        "affected_edge_count="
        f"{selected.result.number_of_affected_edges if selected else 0}"
    )
    print(f"optimizer_runtime_ms={elapsed_ms:.3f}")


if __name__ == "__main__":
    main()
