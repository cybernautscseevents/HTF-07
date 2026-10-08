"""Run the deterministic AEGIS intervention benchmark.

Usage:
    python scripts/benchmark_aegis.py
    python scripts/benchmark_aegis.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.evaluation.benchmark import (
    BenchmarkConfig,
    run_benchmark,
    to_jsonable,
)
from backend.app.evaluation.forecast_benchmark import (
    forecast_to_jsonable,
    run_forecast_benchmark,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark AEGIS intervention strategies.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--forecast", action="store_true", help="Compare Observed-world vs Forecast-aware AEGIS.")
    args = parser.parse_args()

    if args.forecast:
        report = run_forecast_benchmark(BenchmarkConfig())
        if args.json:
            print(json.dumps(forecast_to_jsonable(report), indent=2, sort_keys=True))
            return
        print("=========================================================================================")
        print("AEGIS-Flow Benchmark: Observed-World vs. Forecast-Aware Counterfactual Interdiction")
        print("=========================================================================================")
        print("Strategy | Scenarios | Feasible | Exp Recovery | Min Recovery | Exp Collateral | Max Collateral | Stability | Latency (ms)")
        for agg in report.aggregates:
            display_name = (
                f"{agg.strategy_name} (oracle ref)"
                if agg.strategy_name == "observed_world_aegis"
                else agg.strategy_name
            )
            print(
                f"{display_name:32} | {agg.total_scenarios:9} | {agg.feasible_count:8} | "
                f"{agg.total_expected_recovery:12} | {agg.total_worst_case_recovery:12} | "
                f"{agg.total_expected_collateral:14} | {agg.total_worst_case_collateral:14} | "
                f"{agg.average_intervention_stability:9.1%} | {agg.total_runtime_ms:10.2f}"
            )
        print("\nPer-Scenario Comparison (Observed Realized vs Forecast Exp / Realized):")
        print("Scenario | Observed Recovery | Forecast Exp / Realized | Forecast Max Collateral | Futures | Notes")
        for sc in report.scenarios:
            obs = sc.observed_world_aegis
            fc = sc.forecast_aware_aegis
            notes = ", ".join(sc.comparison_notes) or "ok"
            print(
                f"{sc.scenario_type:28} | {obs.realized_observed_recovery:10} | "
                f"{fc.expected_illicit_recovery:10} / {fc.realized_observed_recovery:10} | "
                f"{fc.worst_case_legitimate_collateral:10} | {fc.futures_evaluated_count:7} | {notes}"
            )
        print("\nLimitations:")
        for lim in report.limitations:
            print(f"- {lim}")
        return

    report = run_benchmark(BenchmarkConfig())
    if args.json:
        print(json.dumps(to_jsonable(report), indent=2, sort_keys=True))
        return
    print("AEGIS-Flow Evaluation & Benchmark")
    print("Strategy | Scenarios | Feasible | Recovery | Collateral | Efficiency | Accounts | Edges | Runtime (ms)")
    for result in report.aggregates:
        efficiency = "undefined" if result.efficiency is None else str(result.efficiency)
        print(
            f"{result.strategy} | {result.scenarios} | {result.feasible_recommendations} | "
            f"{result.recovery} | {result.collateral} | {efficiency} | "
            f"{result.accounts} | {result.edges} | {result.runtime_ms}"
        )
    print("\nScenario findings:")
    for scenario in report.scenarios:
        findings = ", ".join(scenario.findings) or "none"
        print(f"{scenario.scenario_type}: {findings}")
    print("\nLimitations:")
    for limitation in report.limitations:
        print(f"- {limitation}")


if __name__ == "__main__":
    main()
