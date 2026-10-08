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


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark AEGIS intervention strategies.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()
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
