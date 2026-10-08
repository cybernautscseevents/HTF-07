from backend.app.evaluation.benchmark import BenchmarkConfig, run_benchmark, to_jsonable


def test_benchmark_covers_all_scenarios_and_is_structurally_deterministic():
    first = run_benchmark(BenchmarkConfig(seed=42))
    second = run_benchmark(BenchmarkConfig(seed=42))
    assert sorted(item.scenario_type for item in first.scenarios) == [
        "benign_high_volume_merchant",
        "cold_start",
        "commingling",
        "cross_bank",
        "fan_in",
        "fan_out",
        "fan_out_fan_in",
        "rapid_pass_through",
        "simple_chain",
        "smurfing",
    ]
    assert len(first.scenarios) == 10
    assert first.metadata == second.metadata
    assert [
        (item.scenario_id, item.strategy, item.illicit_capital_intercepted)
        for scenario in first.scenarios
        for item in scenario.strategies
    ] == [
        (item.scenario_id, item.strategy, item.illicit_capital_intercepted)
        for scenario in second.scenarios
        for item in scenario.strategies
    ]
    assert to_jsonable(first)["analysis"]["policy_compliance"]["aegis"] == "0.8"
