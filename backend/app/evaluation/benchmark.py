"""Reproducible benchmark runner for intervention strategies."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from time import perf_counter
from typing import Any, Callable

from backend.app.counterfactual.candidates import generate_candidates
from backend.app.counterfactual.simulator import CounterfactualSimulator
from backend.app.evaluation.baselines import BASELINE_SELECTORS
from backend.app.evaluation.metrics import aggregate_efficiency, efficiency
from backend.app.evaluation.models import (
    AggregateResult,
    BenchmarkReport,
    BenchmarkScenario,
    ScenarioResult,
    StrategyResult,
)
from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.optimization import (
    MultiObjectiveInterventionOptimizer,
    ObservedFutureCounterfactualEvaluator,
    OptimizationConstraints,
)
from backend.app.taint.engine import TaintEngine
from backend.app.taint.models import TaintSeed
from scripts.generator import generate_synthetic_world

RiskScorer = Callable[[str, TemporalGraph, datetime], Decimal]

STRATEGY_DEFINITIONS = {
    "highest_risk": "Feasible account hold with the highest risk score known at the simulation timestamp.",
    "highest_tainted_balance": "Feasible account hold with the largest current modeled tainted balance.",
    "highest_transaction_value": "Feasible account hold with the largest future outbound transaction value.",
    "maximum_immediate_recovery": "Feasible candidate with the largest simulated intercepted illicit capital.",
    "aegis": "Existing MultiObjectiveInterventionOptimizer using recovery, collateral, and scope Pareto objectives.",
}


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    seed: int = 42
    scenario_families: tuple[str, ...] | None = None
    constraints: OptimizationConstraints = OptimizationConstraints()


def _default_risk_score(account_id: str, graph: TemporalGraph, timestamp: datetime) -> Decimal:
    """Deterministic observable score used when no trained scorer is injected.

    The score is intentionally derived only from causal graph features. A
    production run should inject the project's fitted ML risk model.
    """
    incoming = graph.incoming(account_id, end=timestamp, active_only=True)
    outgoing = graph.outgoing(account_id, end=timestamp, active_only=True)
    # This fallback is only an executable deterministic scorer for the
    # synthetic CLI. A fitted ML scorer should be injected for ML evaluation.
    signal = 2 * len(outgoing) + len(incoming)
    return Decimal(signal) / Decimal(max(1, len(incoming) + len(outgoing)))


def _selected_result(
    strategy: str,
    scenario: BenchmarkScenario,
    selected: Any,
    elapsed_ms: Decimal,
) -> StrategyResult:
    if selected is None:
        return StrategyResult(
            strategy, scenario.scenario_id, None, False, 0, 0, None, None,
            0, 0, 0, elapsed_ms, False, 0, "No feasible intervention.",
        )
    result = selected.result
    intercepted = result.modeled_tainted_capital_intercepted
    collateral = result.modeled_legitimate_capital_affected
    matching = [
        item for item in scenario.evaluations
        if item.feasible
        and item.result.modeled_tainted_capital_intercepted == intercepted
        and item.result.modeled_legitimate_capital_affected == collateral
    ]
    return StrategyResult(
        strategy=strategy,
        scenario_id=scenario.scenario_id,
        selected_intervention_id=selected.intervention_id,
        feasible=True,
        illicit_capital_intercepted=intercepted,
        legitimate_capital_affected=collateral,
        efficiency=efficiency(intercepted, collateral),
        illicit_per_rupee_legitimate=efficiency(intercepted, collateral),
        affected_accounts=result.number_of_affected_accounts,
        affected_edges=result.number_of_affected_edges,
        intervention_count=1,
        decision_latency_ms=elapsed_ms,
        pareto_efficient=selected.pareto_rank == 0,
        tie_count=len(matching),
        reason="Selected from the common evaluated candidate set.",
    )


def _scenario_findings(results: tuple[StrategyResult, ...]) -> tuple[str, ...]:
    by_name = {item.strategy: item for item in results}
    findings: list[str] = []
    risk = by_name["highest_risk"]
    taint = by_name["highest_tainted_balance"]
    recovery = by_name["maximum_immediate_recovery"]
    aegis = by_name["aegis"]
    if risk.feasible and taint.feasible and risk.illicit_capital_intercepted < taint.illicit_capital_intercepted:
        findings.append("highest_risk_loses_to_taint")
    if recovery.feasible and aegis.feasible and recovery.legitimate_capital_affected > aegis.legitimate_capital_affected:
        findings.append("maximum_recovery_has_more_collateral")
    if aegis.feasible and recovery.feasible and aegis.illicit_capital_intercepted < recovery.illicit_capital_intercepted:
        findings.append("aegis_lower_recovery")
    if not aegis.feasible:
        findings.append("no_feasible_aegis_intervention")
    if any(item.tie_count > 1 for item in results):
        findings.append("multiple_strategies_tie")
    if any(item.feasible and item.legitimate_capital_affected == 0 for item in results):
        findings.append("zero_collateral_intervention")
    return tuple(sorted(set(findings)))


def _aggregate(name: str, results: list[StrategyResult], cold_start_count: int) -> AggregateResult:
    recovery = sum(item.illicit_capital_intercepted for item in results)
    collateral = sum(item.legitimate_capital_affected for item in results)
    return AggregateResult(
        strategy=name,
        scenarios=len(results),
        feasible_recommendations=sum(item.feasible for item in results),
        recovery=recovery,
        collateral=collateral,
        efficiency=aggregate_efficiency(recovery, collateral),
        accounts=sum(item.affected_accounts for item in results),
        edges=sum(item.affected_edges for item in results),
        runtime_ms=sum((item.decision_latency_ms for item in results), Decimal(0)),
        pareto_efficient_selections=sum(item.pareto_efficient for item in results),
        cold_start_scenarios=cold_start_count,
    )


def run_benchmark(
    config: BenchmarkConfig | None = None,
    risk_scorer: RiskScorer | None = None,
) -> BenchmarkReport:
    """Run all strategies over the same generated scenarios and evaluations."""
    config = config or BenchmarkConfig()
    scorer = risk_scorer or _default_risk_score
    world = generate_synthetic_world(config.seed, scenario_families=config.scenario_families)
    scenario_reports: list[ScenarioResult] = []

    for scenario_type, generated in sorted(world.scenarios.items()):
        graph = TemporalGraph()
        graph.build_case(generated.transactions)
        seed_events = [
            event for event in generated.transactions
            if event.transaction_id in generated.truth.seed_transaction_ids
        ]
        if not seed_events or generated.truth.case_id is None:
            simulation_timestamp = min(event.occurred_at for event in generated.transactions)
            taint_seeds = []
        else:
            simulation_timestamp = min(event.occurred_at for event in seed_events)
            taint_seeds = [
                TaintSeed(generated.truth.case_id, event.transaction_id, event.amount_minor_units)
                for event in seed_events
            ]
        taint = TaintEngine().run(graph, taint_seeds)
        candidates = tuple(generate_candidates(graph, taint, simulation_timestamp))
        optimizer = MultiObjectiveInterventionOptimizer(
            ObservedFutureCounterfactualEvaluator(CounterfactualSimulator(graph, taint))
        )
        started = perf_counter()
        optimization = optimizer.optimize(candidates, simulation_timestamp, config.constraints)
        aegis_elapsed = Decimal(str((perf_counter() - started) * 1000))
        balances = {
            balance.account_id: balance.tainted_balance_minor_units
            for balance in taint.current_tainted_accounts()
        }
        values = {
            account: max(
                (edge.amount_minor_units for edge in graph.outgoing(
                    account, start=simulation_timestamp, active_only=True
                ) if edge.occurred_at > simulation_timestamp),
                default=0,
            )
            for account in graph.accounts
        }
        institutions = {
            item.account_id: item.institution
            for item in generated.accounts if item.institution is not None
        }
        # Institution data is observable metadata, not ScenarioTruth.
        del institutions
        risk_scores = {
            account: scorer(account, graph, simulation_timestamp)
            for account in graph.accounts
        }
        benchmark_scenario = BenchmarkScenario(
            generated.scenario_id, scenario_type, simulation_timestamp, candidates,
            optimization.evaluations, config.constraints, risk_scores, balances, values,
            scenario_type == "cold_start",
        )
        results: list[StrategyResult] = []
        for name, selector in BASELINE_SELECTORS.items():
            start = perf_counter()
            selected = selector(
                optimization.evaluations, risk_scores, balances, values
            )
            elapsed = Decimal(str((perf_counter() - start) * 1000))
            results.append(_selected_result(name, benchmark_scenario, selected, elapsed))
        results.append(_selected_result("aegis", benchmark_scenario, optimization.selected_evaluation, aegis_elapsed))
        ordered = tuple(sorted(results, key=lambda item: item.strategy))
        scenario_reports.append(ScenarioResult(
            generated.scenario_id, scenario_type, scenario_type == "cold_start",
            ordered, _scenario_findings(ordered),
        ))

    scenario_reports.sort(key=lambda item: item.scenario_id)
    by_strategy: dict[str, list[StrategyResult]] = {name: [] for name in STRATEGY_DEFINITIONS}
    for scenario in scenario_reports:
        for result in scenario.strategies:
            by_strategy[result.strategy].append(result)
    cold_start_count = sum(scenario.cold_start for scenario in scenario_reports)
    aggregates = tuple(
        _aggregate(name, by_strategy[name], cold_start_count)
        for name in sorted(STRATEGY_DEFINITIONS)
    )
    analysis: dict[str, Any] = {
        "recovery_advantage": {},
        "collateral_reduction": {},
        "efficiency_improvement": {},
        "policy_compliance": {
            name: (
                str(Decimal(sum(item.feasible for item in values)) / Decimal(len(values)))
                if values else "0"
            )
            for name, values in sorted(by_strategy.items())
        },
        "pareto_behavior": {
            "aegis_pareto_efficient_count": sum(
                item.pareto_efficient for item in by_strategy["aegis"]
            ),
            "aegis_scenario_count": len(by_strategy["aegis"]),
        },
    }
    for scenario in scenario_reports:
        by_name = {item.strategy: item for item in scenario.strategies}
        aegis = by_name["aegis"]
        for name in sorted(STRATEGY_DEFINITIONS):
            if name == "aegis":
                continue
            baseline = by_name[name]
            analysis["recovery_advantage"].setdefault(name, {})[scenario.scenario_id] = (
                aegis.illicit_capital_intercepted - baseline.illicit_capital_intercepted
            )
            analysis["collateral_reduction"].setdefault(name, {})[scenario.scenario_id] = (
                baseline.legitimate_capital_affected - aegis.legitimate_capital_affected
            )
            analysis["efficiency_improvement"].setdefault(name, {})[scenario.scenario_id] = (
                None if aegis.efficiency is None or baseline.efficiency is None
                else str(aegis.efficiency - baseline.efficiency)
            )
    return BenchmarkReport(
        metadata={
            "seed": config.seed,
            "scenario_count": len(scenario_reports),
            "generated_at": "deterministic-run",
            "money_unit": "minor units (paise)",
        },
        scenarios=tuple(scenario_reports),
        aggregates=aggregates,
        strategy_definitions=dict(STRATEGY_DEFINITIONS),
        analysis=analysis,
        limitations=(
            "Synthetic data and observed-future counterfactuals are not production outcomes.",
            "This benchmark compares AEGIS against deterministic baseline strategies on the project's synthetic evaluation environment. It does not establish superiority over proprietary production systems.",
        ),
    )


def to_jsonable(report: BenchmarkReport) -> dict[str, Any]:
    """Serialize exact Decimal values as strings and tuples as JSON arrays."""
    def convert(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, tuple):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        if hasattr(value, "__dataclass_fields__"):
            return {key: convert(item) for key, item in asdict(value).items()}
        return value
    return convert(report)
