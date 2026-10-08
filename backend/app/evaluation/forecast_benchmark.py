"""Benchmark comparing Observed-world AEGIS and Forecast-aware AEGIS.

Extends the benchmark layer across all 10 canonical synthetic scenario families:
1. simple_chain
2. fan_out
3. fan_in
4. fan_out_fan_in
5. commingling
6. cold_start
7. cross_bank
8. smurfing
9. rapid_pass_through
10. benign_high_volume_merchant

Measures:
- expected illicit recovery
- worst-case illicit recovery
- expected legitimate collateral
- worst-case legitimate collateral
- constraint satisfaction probability
- intervention stability across futures
- forecast generation runtime
- total decision latency
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from time import perf_counter
from typing import Any

from backend.app.counterfactual.candidates import generate_candidates
from backend.app.counterfactual.simulator import CounterfactualSimulator
from backend.app.evaluation.benchmark import BenchmarkConfig
from backend.app.forecast import (
    ForecastAwareCounterfactualEvaluator,
    ForecastAwareCounterfactualResult,
    select_robust_intervention,
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


@dataclass(frozen=True, slots=True)
class EvaluatedStrategyMetrics:
    """Detailed performance metrics for one strategy on one scenario."""

    strategy_name: str
    scenario_id: str
    scenario_type: str
    selected_intervention_id: str | None
    target_account_id: str | None
    feasible: bool
    expected_illicit_recovery: int
    worst_case_illicit_recovery: int
    realized_observed_recovery: int
    expected_legitimate_collateral: int
    worst_case_legitimate_collateral: int
    realized_observed_collateral: int
    constraint_satisfaction_probability: float
    intervention_stability_across_futures: float
    forecast_generation_runtime_ms: Decimal
    total_decision_latency_ms: Decimal
    futures_evaluated_count: int
    forecast_status: str


@dataclass(frozen=True, slots=True)
class ScenarioComparisonResult:
    """Side-by-side comparison for one scenario."""

    scenario_id: str
    scenario_type: str
    observed_world_aegis: EvaluatedStrategyMetrics
    forecast_aware_aegis: EvaluatedStrategyMetrics
    comparison_notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AggregateComparisonResult:
    """Aggregate metrics over all evaluated scenarios."""

    strategy_name: str
    total_scenarios: int
    feasible_count: int
    total_expected_recovery: int
    total_worst_case_recovery: int
    total_realized_observed_recovery: int
    total_expected_collateral: int
    total_worst_case_collateral: int
    total_realized_observed_collateral: int
    average_constraint_satisfaction: float
    average_intervention_stability: float
    total_runtime_ms: Decimal


@dataclass(frozen=True, slots=True)
class ForecastBenchmarkReport:
    """Complete report comparing observed-world AEGIS vs. forecast-aware AEGIS."""

    metadata: dict[str, Any]
    scenarios: tuple[ScenarioComparisonResult, ...]
    aggregates: tuple[AggregateComparisonResult, ...]
    limitations: tuple[str, ...]


def run_forecast_benchmark(
    config: BenchmarkConfig | None = None,
) -> ForecastBenchmarkReport:
    """Run comparative evaluation across all 10 scenario families."""
    config = config or BenchmarkConfig()
    world = generate_synthetic_world(config.seed, scenario_families=config.scenario_families)

    scenario_comparisons: list[ScenarioComparisonResult] = []

    for scenario_type, generated in sorted(world.scenarios.items()):
        # Build ground-truth graph
        graph = TemporalGraph()
        graph.build_case(generated.transactions)

        seed_events = [
            event for event in generated.transactions
            if event.transaction_id in generated.truth.seed_transaction_ids
        ]

        if not seed_events or generated.truth.case_id is None:
            simulation_timestamp = min(event.occurred_at for event in generated.transactions)
            taint_seeds: list[TaintSeed] = []
        else:
            simulation_timestamp = min(event.occurred_at for event in seed_events)
            taint_seeds = [
                TaintSeed(generated.truth.case_id, event.transaction_id, event.amount_minor_units)
                for event in seed_events
            ]

        # Ground truth baseline taint (for observed replay)
        observed_taint = TaintEngine().run(graph, taint_seeds)
        observed_simulator = CounterfactualSimulator(graph, observed_taint)

        # ── Strategy A: Observed-World AEGIS ──────────────────────────────
        observed_evaluator = ObservedFutureCounterfactualEvaluator(observed_simulator)
        observed_candidates = tuple(
            generate_candidates(graph, observed_taint, simulation_timestamp)
        )
        observed_optimizer = MultiObjectiveInterventionOptimizer(observed_evaluator)

        obs_start = perf_counter()
        obs_opt = observed_optimizer.optimize(
            observed_candidates, simulation_timestamp, config.constraints
        )
        obs_elapsed_ms = Decimal(str((perf_counter() - obs_start) * 1000))

        obs_selected = obs_opt.selected_evaluation
        if obs_selected is not None:
            res_a = obs_selected.result
            target_a = obs_selected.candidate.target_account_id
            obs_metrics = EvaluatedStrategyMetrics(
                strategy_name="observed_world_aegis",
                scenario_id=generated.scenario_id,
                scenario_type=scenario_type,
                selected_intervention_id=obs_selected.intervention_id,
                target_account_id=target_a,
                feasible=obs_selected.feasible,
                expected_illicit_recovery=res_a.modeled_tainted_capital_intercepted,
                worst_case_illicit_recovery=res_a.modeled_tainted_capital_intercepted,
                realized_observed_recovery=res_a.modeled_tainted_capital_intercepted,
                expected_legitimate_collateral=res_a.modeled_legitimate_capital_affected,
                worst_case_legitimate_collateral=res_a.modeled_legitimate_capital_affected,
                realized_observed_collateral=res_a.modeled_legitimate_capital_affected,
                constraint_satisfaction_probability=1.0 if obs_selected.feasible else 0.0,
                intervention_stability_across_futures=1.0 if res_a.modeled_tainted_capital_intercepted > 0 else 0.0,
                forecast_generation_runtime_ms=Decimal("0.0"),
                total_decision_latency_ms=obs_elapsed_ms,
                futures_evaluated_count=1,
                forecast_status="oracle_observed_future_reference",
            )
        else:
            obs_metrics = EvaluatedStrategyMetrics(
                strategy_name="observed_world_aegis",
                scenario_id=generated.scenario_id,
                scenario_type=scenario_type,
                selected_intervention_id=None,
                target_account_id=None,
                feasible=False,
                expected_illicit_recovery=0,
                worst_case_illicit_recovery=0,
                realized_observed_recovery=0,
                expected_legitimate_collateral=0,
                worst_case_legitimate_collateral=0,
                realized_observed_collateral=0,
                constraint_satisfaction_probability=0.0,
                intervention_stability_across_futures=0.0,
                forecast_generation_runtime_ms=Decimal("0.0"),
                total_decision_latency_ms=obs_elapsed_ms,
                futures_evaluated_count=1,
                forecast_status="oracle_observed_future_reference",
            )

        # ── Strategy B: Forecast-Aware AEGIS ──────────────────────────────
        fc_evaluator = ForecastAwareCounterfactualEvaluator(
            graph=graph,
            taint_seeds=taint_seeds,
            simulation_timestamp=simulation_timestamp,
        )
        fc_candidates = tuple(fc_evaluator.generate_candidates())
        fc_optimizer = MultiObjectiveInterventionOptimizer(fc_evaluator)

        fc_start = perf_counter()
        fc_opt = fc_optimizer.optimize(
            fc_candidates, simulation_timestamp, config.constraints
        )
        fc_decision_elapsed_ms = Decimal(str((perf_counter() - fc_start) * 1000))
        fc_total_latency_ms = (
            fc_evaluator.forecast_generation_runtime_ms + fc_decision_elapsed_ms
        )

        fc_selected = (
            select_robust_intervention(fc_opt.feasible_evaluations, config.constraints)
            if fc_opt.feasible_evaluations
            else fc_opt.selected_evaluation
        )
        if fc_selected is not None:
            res_b = fc_selected.result
            assert isinstance(res_b, ForecastAwareCounterfactualResult)
            target_b = fc_selected.candidate.target_account_id

            # Evaluate the chosen forecast-aware candidate against observed reality
            realized_cf = observed_simulator.simulate(
                fc_selected.candidate, simulation_timestamp
            )

            fc_metrics = EvaluatedStrategyMetrics(
                strategy_name="forecast_aware_aegis",
                scenario_id=generated.scenario_id,
                scenario_type=scenario_type,
                selected_intervention_id=fc_selected.intervention_id,
                target_account_id=target_b,
                feasible=fc_selected.feasible,
                expected_illicit_recovery=res_b.expected_illicit_interception,
                worst_case_illicit_recovery=res_b.worst_case_illicit_interception,
                realized_observed_recovery=realized_cf.modeled_tainted_capital_intercepted,
                expected_legitimate_collateral=res_b.expected_legitimate_impact,
                worst_case_legitimate_collateral=res_b.worst_case_legitimate_impact,
                realized_observed_collateral=realized_cf.modeled_legitimate_capital_affected,
                constraint_satisfaction_probability=res_b.constraint_satisfaction_probability,
                intervention_stability_across_futures=res_b.constraint_satisfaction_probability,
                forecast_generation_runtime_ms=fc_evaluator.forecast_generation_runtime_ms,
                total_decision_latency_ms=fc_total_latency_ms,
                futures_evaluated_count=len(fc_evaluator.scenarios),
                forecast_status=fc_evaluator.forecast_status,
            )
        else:
            fc_metrics = EvaluatedStrategyMetrics(
                strategy_name="forecast_aware_aegis",
                scenario_id=generated.scenario_id,
                scenario_type=scenario_type,
                selected_intervention_id=None,
                target_account_id=None,
                feasible=False,
                expected_illicit_recovery=0,
                worst_case_illicit_recovery=0,
                realized_observed_recovery=0,
                expected_legitimate_collateral=0,
                worst_case_legitimate_collateral=0,
                realized_observed_collateral=0,
                constraint_satisfaction_probability=0.0,
                intervention_stability_across_futures=0.0,
                forecast_generation_runtime_ms=fc_evaluator.forecast_generation_runtime_ms,
                total_decision_latency_ms=fc_total_latency_ms,
                futures_evaluated_count=len(fc_evaluator.scenarios),
                forecast_status=fc_evaluator.forecast_status,
            )

        # Comparative analysis notes
        notes: list[str] = ["observed_oracle_reference"]
        if fc_metrics.feasible and obs_metrics.feasible:
            if fc_metrics.realized_observed_recovery == obs_metrics.realized_observed_recovery:
                notes.append("identical_realized_recovery")
            elif fc_metrics.realized_observed_recovery < obs_metrics.realized_observed_recovery:
                notes.append("forecast_underperforms_due_to_prediction_gap")
            else:
                notes.append("forecast_exceeds_observed")

            if fc_metrics.worst_case_legitimate_collateral > obs_metrics.expected_legitimate_collateral:
                notes.append("forecast_guards_worst_case_collateral")
        elif not fc_metrics.feasible and not obs_metrics.feasible:
            notes.append("both_infeasible_or_negative_control")
        elif obs_metrics.feasible and not fc_metrics.feasible:
            notes.append("forecast_conservative_infeasibility")

        scenario_comparisons.append(
            ScenarioComparisonResult(
                scenario_id=generated.scenario_id,
                scenario_type=scenario_type,
                observed_world_aegis=obs_metrics,
                forecast_aware_aegis=fc_metrics,
                comparison_notes=tuple(notes),
            )
        )

    # Compute aggregates
    def _make_aggregate(name: str, metrics_list: list[EvaluatedStrategyMetrics]) -> AggregateComparisonResult:
        n = len(metrics_list)
        return AggregateComparisonResult(
            strategy_name=name,
            total_scenarios=n,
            feasible_count=sum(m.feasible for m in metrics_list),
            total_expected_recovery=sum(m.expected_illicit_recovery for m in metrics_list),
            total_worst_case_recovery=sum(m.worst_case_illicit_recovery for m in metrics_list),
            total_realized_observed_recovery=sum(m.realized_observed_recovery for m in metrics_list),
            total_expected_collateral=sum(m.expected_legitimate_collateral for m in metrics_list),
            total_worst_case_collateral=sum(m.worst_case_legitimate_collateral for m in metrics_list),
            total_realized_observed_collateral=sum(m.realized_observed_collateral for m in metrics_list),
            average_constraint_satisfaction=round(sum(m.constraint_satisfaction_probability for m in metrics_list) / max(1, n), 4),
            average_intervention_stability=round(sum(m.intervention_stability_across_futures for m in metrics_list) / max(1, n), 4),
            total_runtime_ms=sum((m.total_decision_latency_ms for m in metrics_list), Decimal(0)),
        )

    obs_list = [sc.observed_world_aegis for sc in scenario_comparisons]
    fc_list = [sc.forecast_aware_aegis for sc in scenario_comparisons]

    aggregates = (
        _make_aggregate("observed_world_aegis", obs_list),
        _make_aggregate("forecast_aware_aegis", fc_list),
    )

    return ForecastBenchmarkReport(
        metadata={
            "seed": config.seed,
            "scenario_count": len(scenario_comparisons),
            "generated_at": "deterministic-forecast-run",
            "money_unit": "minor units (paise)",
        },
        scenarios=tuple(scenario_comparisons),
        aggregates=aggregates,
        limitations=(
            "Observed-world counterfactuals serve as an oracle/observed-future reference because they evaluate interventions against observed ground-truth transactions that were unavailable at simulation timestamp T.",
            "Forecast-aware counterfactuals evaluate plausible trajectories based solely on state <= T without future oracle leakage.",
            "In cold-start or zero-telemetry scenarios, ML prediction may exhibit coverage gaps relative to observed future ground-truth.",
            "Amount pass-through is modeled assuming 100% forwardable tainted capital pass-through, not settlement dynamics.",
        ),
    )


def forecast_to_jsonable(report: ForecastBenchmarkReport) -> dict[str, Any]:
    """Serialize benchmark report to JSON-serializable structure."""
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
