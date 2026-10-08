"""Deterministic unit & integration tests for Forecast-Aware Counterfactual Interdiction.

Verifies:
1. Top-K path generation bounds
2. Beam-search ordering and determinism
3. Probability ordering
4. Duplicate path prevention
5. Temporal causality (occurred_at > simulation_timestamp)
6. Bounded horizon (max_depth)
7. No future-data leakage
8. Forecast vs. observed event distinction
9. Integer minor-unit arithmetic
10. Insufficient prediction evidence state
11. Zero candidate paths
12. Single-path forecast
13. Multiple-path forecast
14. Probability-weighted metrics calculation
15. Worst-case robustness metrics
16. Deterministic repeated runs
17. Baseline graph & taint immutability
18. Existing Intervention Optimizer compatibility
19. Forecast benchmark coverage
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.app.counterfactual.models import (
    CounterfactualResult,
    InterventionCandidate,
    InterventionType,
)
from backend.app.evaluation.benchmark import BenchmarkConfig
from backend.app.evaluation.forecast_benchmark import (
    ForecastBenchmarkReport,
    run_forecast_benchmark,
)
from backend.app.forecast import (
    ForecastAwareCounterfactualEvaluator,
    ForecastAwareCounterfactualResult,
    ForecastGeneratorConfig,
    ForecastPath,
    ForecastPathGenerator,
    ForecastStatus,
    ForecastTransactionEvent,
    generate_forecast_candidates,
    robust_selection_sort_key,
    select_robust_intervention,
)
from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.ml.next_hop import NextHopPredictor
from backend.app.ml.schemas import NextHopCandidate, NextHopPrediction
from backend.app.optimization import (
    MultiObjectiveInterventionOptimizer,
    OptimizationConstraints,
    OptimizationResult,
)
from backend.app.taint.engine import TaintEngine
from backend.app.taint.models import TaintSeed
from contracts.account import AccountReference
from contracts.enums import (
    EventOrigin,
    TransactionChannel,
    TransactionStatus,
)
from contracts.transaction import TransactionEvent

UTC = timezone.utc


def _make_event(
    event_id: str,
    sender_id: str,
    receiver_id: str,
    amount: int,
    occurred_at: datetime,
) -> TransactionEvent:
    return TransactionEvent(
        event_id=event_id,
        transaction_id=f"tx-{event_id}",
        sender=AccountReference(account_id=sender_id, institution="BANK_A"),
        receiver=AccountReference(account_id=receiver_id, institution="BANK_B"),
        amount_minor_units=amount,
        currency="INR",
        occurred_at=occurred_at,
        observed_at=occurred_at + timedelta(seconds=1),
        status=TransactionStatus.COMPLETED,
        channel=TransactionChannel.UPI,
        origin=EventOrigin.BANK_FEED,
    )


class MockPredictor:
    """Deterministic mock predictor for testing beam search logic."""

    def __init__(self, candidate_map: dict[str, list[tuple[str, float]]]) -> None:
        self.candidate_map = candidate_map
        self.model_version = "mock-v1"

    def predict_next_hop(
        self,
        graph: TemporalGraph,
        source_account_id: str,
        as_of_time: datetime,
        candidate_pool: list[str] | None = None,
        institution_map: dict[str, str] | None = None,
        top_k: int = 5,
    ) -> NextHopPrediction:
        raw = self.candidate_map.get(source_account_id, [])
        candidates = [
            NextHopCandidate(
                account_id=dest,
                predicted_probability=prob,
                rank=idx + 1,
                candidate_signals={},
            )
            for idx, (dest, prob) in enumerate(raw[:top_k])
        ]
        top_1 = candidates[0].account_id if candidates else None
        return NextHopPrediction(
            source_account_id=source_account_id,
            candidates=candidates,
            model_version=self.model_version,
            prediction_timestamp=as_of_time,
            top_1_account_id=top_1,
        )


# ── 1. Top-K Path Generation ─────────────────────────────────────────────────


def test_top_k_path_generation() -> None:
    """Verifies that generated paths do not exceed the configured top_k beam limit."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "mule1", 10_000_000, t0))

    mock = MockPredictor(
        {
            "mule1": [("mule2", 0.5), ("mule3", 0.3), ("mule4", 0.15), ("mule5", 0.05)],
        }
    )
    generator = ForecastPathGenerator(
        predictor=mock,  # type: ignore[arg-type]
        config=ForecastGeneratorConfig(top_k=2, max_depth=1),
    )
    paths = generator.generate_paths(
        graph=g,
        active_sources={"mule1": 10_000_000},
        simulation_timestamp=t0,
    )
    assert len(paths) == 2
    assert [p.accounts_sequence for p in paths] == [
        ("mule1", "mule2"),
        ("mule1", "mule3"),
    ]


# ── 2. Beam-Search Ordering & Tie-Breaking ───────────────────────────────────


def test_beam_search_ordering() -> None:
    """Verifies deterministic beam-search expansion and tie-breaking order."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "src", 10_000_000, t0))

    # Tied probabilities: mule_b vs mule_a
    mock = MockPredictor(
        {
            "src": [("mule_b", 0.5), ("mule_a", 0.5)],
        }
    )
    generator = ForecastPathGenerator(
        predictor=mock,  # type: ignore[arg-type]
        config=ForecastGeneratorConfig(top_k=2, max_depth=1),
    )
    paths = generator.generate_paths(
        graph=g,
        active_sources={"src": 10_000_000},
        simulation_timestamp=t0,
    )
    assert len(paths) == 2
    # Deterministic alphabetical tie-breaking for equal probabilities
    assert paths[0].accounts_sequence == ("src", "mule_a")
    assert paths[1].accounts_sequence == ("src", "mule_b")


# ── 3. Probability Ordering ──────────────────────────────────────────────────


def test_probability_ordering() -> None:
    """Verifies that plausible paths are strictly ranked in descending probability."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "src", 10_000_000, t0))

    mock = MockPredictor(
        {
            "src": [("dest_high", 0.7), ("dest_low", 0.3)],
        }
    )
    generator = ForecastPathGenerator(
        predictor=mock,  # type: ignore[arg-type]
        config=ForecastGeneratorConfig(top_k=2, max_depth=1),
    )
    paths = generator.generate_paths(
        graph=g,
        active_sources={"src": 10_000_000},
        simulation_timestamp=t0,
    )
    assert paths[0].cumulative_probability >= paths[1].cumulative_probability
    assert paths[0].destination_account_id == "dest_high"


# ── 4. Duplicate Path Prevention ─────────────────────────────────────────────


def test_duplicate_path_prevention() -> None:
    """Verifies that no duplicate path sequences are generated or retained."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "src", 10_000_000, t0))

    mock = MockPredictor(
        {
            "src": [("dest", 0.8), ("dest", 0.8)],
        }
    )
    generator = ForecastPathGenerator(
        predictor=mock,  # type: ignore[arg-type]
        config=ForecastGeneratorConfig(top_k=3, max_depth=1),
    )
    paths = generator.generate_paths(
        graph=g,
        active_sources={"src": 10_000_000},
        simulation_timestamp=t0,
    )
    # Even if predictor returned duplicate candidate, generator filters duplicates
    assert len(paths) == 1


# ── 5. Temporal Causality ────────────────────────────────────────────────────


def test_temporal_causality() -> None:
    """Verifies that all forecast events occur strictly after simulation_timestamp."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "mule1", 5_000_000, t0))

    mock = MockPredictor(
        {
            "mule1": [("mule2", 0.9)],
            "mule2": [("mule3", 0.8)],
        }
    )
    generator = ForecastPathGenerator(
        predictor=mock,  # type: ignore[arg-type]
        config=ForecastGeneratorConfig(top_k=1, max_depth=2, hop_delay_seconds=120.0),
    )
    paths = generator.generate_paths(
        graph=g,
        active_sources={"mule1": 5_000_000},
        simulation_timestamp=t0,
    )
    scenarios = generator.build_future_scenarios(
        historical_graph=g,
        paths=paths,
        taint_seeds=[TaintSeed("case-1", "tx-e0", 5_000_000)],
        simulation_timestamp=t0,
    )
    assert len(scenarios) == 1
    for fc_evt in scenarios[0].forecast_events:
        assert fc_evt.occurred_at > t0, "Forecast event must occur strictly after t0."


# ── 6. Bounded Horizon ───────────────────────────────────────────────────────


def test_bounded_horizon() -> None:
    """Verifies that path expansion terminates exactly at max_depth."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "m1", 5_000_000, t0))

    mock = MockPredictor(
        {
            "m1": [("m2", 0.9)],
            "m2": [("m3", 0.9)],
            "m3": [("m4", 0.9)],
            "m4": [("m5", 0.9)],
        }
    )
    generator = ForecastPathGenerator(
        predictor=mock,  # type: ignore[arg-type]
        config=ForecastGeneratorConfig(top_k=1, max_depth=3),
    )
    paths = generator.generate_paths(
        graph=g,
        active_sources={"m1": 5_000_000},
        simulation_timestamp=t0,
    )
    assert len(paths) == 1
    assert paths[0].hop_count == 3
    assert paths[0].accounts_sequence == ("m1", "m2", "m3", "m4")


# ── 7. No Future-Data Leakage ────────────────────────────────────────────────


def test_no_future_data_leakage() -> None:
    """Verifies that events occurring after simulation_timestamp do not alter predictions."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g_past = TemporalGraph()
    g_past.add_event(_make_event("e0", "victim", "m1", 5_000_000, t0))

    # Graph with future ground-truth event added
    g_future = TemporalGraph()
    g_future.add_event(_make_event("e0", "victim", "m1", 5_000_000, t0))
    g_future.add_event(
        _make_event("e_future", "m1", "future_leak", 5_000_000, t0 + timedelta(hours=1))
    )

    evaluator_past = ForecastAwareCounterfactualEvaluator(
        graph=g_past,
        taint_seeds=[TaintSeed("case-1", "tx-e0", 5_000_000)],
        simulation_timestamp=t0,
    )
    evaluator_future = ForecastAwareCounterfactualEvaluator(
        graph=g_future,
        taint_seeds=[TaintSeed("case-1", "tx-e0", 5_000_000)],
        simulation_timestamp=t0,
    )

    assert evaluator_past.paths == evaluator_future.paths
    assert evaluator_past.forecast_status == evaluator_future.forecast_status


# ── 8. Forecast vs Observed Event Distinction ────────────────────────────────


def test_forecast_vs_observed_event_distinction() -> None:
    """Verifies that ForecastTransactionEvent is marked synthetic and distinct from canonical events."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    fc = ForecastTransactionEvent(
        event_id="fc-evt-01",
        transaction_id="fc-tx-01",
        sender_account_id="m1",
        receiver_account_id="m2",
        amount_minor_units=1_000_000,
        currency="INR",
        occurred_at=t0 + timedelta(minutes=5),
        probability=0.85,
        path_id="path-01",
        hop_index=1,
    )
    assert fc.probability == 0.85
    assert fc.hop_index == 1
    assert fc.event_id.startswith("fc-evt-")

    sim_event = fc.to_simulation_event()
    assert sim_event.origin == EventOrigin.SYNTHETIC
    assert sim_event.status == TransactionStatus.COMPLETED


# ── 9. Integer Amount Handling ───────────────────────────────────────────────


def test_integer_amount_handling() -> None:
    """Verifies exact integer minor-unit arithmetic throughout path creation and simulation."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    amount_paise = 12_345_678  # ₹1,23,456.78
    g.add_event(_make_event("e0", "victim", "m1", amount_paise, t0))

    evaluator = ForecastAwareCounterfactualEvaluator(
        graph=g,
        taint_seeds=[TaintSeed("case-1", "tx-e0", amount_paise)],
        simulation_timestamp=t0,
    )
    for p in evaluator.paths:
        for hop in p.hops:
            assert isinstance(hop.amount_minor_units, int)
            assert hop.amount_minor_units == amount_paise

    res = evaluator.evaluate(
        InterventionCandidate(InterventionType.ACCOUNT_HOLD, target_account_id="m1"),
        simulation_timestamp=t0,
    )
    assert isinstance(res.modeled_tainted_capital_intercepted, int)
    assert isinstance(res.modeled_legitimate_capital_affected, int)


# ── 10. Insufficient Prediction Evidence ─────────────────────────────────────


def test_insufficient_prediction_evidence() -> None:
    """Verifies that when zero forwardable taint exists, system returns insufficient evidence state."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "clean_a", "clean_b", 500_000, t0))

    # No seeds -> no taint
    evaluator = ForecastAwareCounterfactualEvaluator(
        graph=g,
        taint_seeds=[],
        simulation_timestamp=t0,
    )
    assert evaluator.forecast_status == ForecastStatus.INSUFFICIENT_EVIDENCE.value
    assert len(evaluator.scenarios) == 0

    res = evaluator.evaluate(
        InterventionCandidate(InterventionType.ACCOUNT_HOLD, target_account_id="clean_b"),
        simulation_timestamp=t0,
    )
    assert isinstance(res, ForecastAwareCounterfactualResult)
    assert res.forecast_status == ForecastStatus.INSUFFICIENT_EVIDENCE.value
    assert res.expected_illicit_interception == 0
    assert "insufficient prediction evidence" in res.explanation


# ── 11. Zero Candidate Paths ─────────────────────────────────────────────────


def test_zero_candidate_paths() -> None:
    """Verifies behavior when source is tainted but predictor yields zero candidates."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "m1", 5_000_000, t0))

    mock_empty = MockPredictor({"m1": []})
    evaluator = ForecastAwareCounterfactualEvaluator(
        graph=g,
        taint_seeds=[TaintSeed("case-1", "tx-e0", 5_000_000)],
        simulation_timestamp=t0,
        predictor=mock_empty,  # type: ignore[arg-type]
    )
    assert evaluator.forecast_status == ForecastStatus.NO_CANDIDATE_PATHS.value
    assert len(evaluator.scenarios) == 0


# ── 12. Single-Path Forecast ─────────────────────────────────────────────────


def test_one_path_forecast() -> None:
    """Verifies single-path forecast evaluation."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "m1", 5_000_000, t0))

    mock = MockPredictor({"m1": [("m2", 1.0)]})
    evaluator = ForecastAwareCounterfactualEvaluator(
        graph=g,
        taint_seeds=[TaintSeed("case-1", "tx-e0", 5_000_000)],
        simulation_timestamp=t0,
        predictor=mock,  # type: ignore[arg-type]
        config=ForecastGeneratorConfig(top_k=1, max_depth=1),
    )
    assert len(evaluator.scenarios) == 1
    assert evaluator.scenarios[0].normalized_weight == 1.0

    res = evaluator.evaluate(
        InterventionCandidate(InterventionType.ACCOUNT_HOLD, target_account_id="m1"),
        simulation_timestamp=t0,
    )
    assert res.modeled_tainted_capital_intercepted == 5_000_000
    assert res.worst_case_illicit_interception == 5_000_000
    assert res.best_case_illicit_interception == 5_000_000


# ── 13. Multiple-Path Forecast ───────────────────────────────────────────────


def test_multiple_path_forecast() -> None:
    """Verifies multiple plausible paths with normalized weights summing to 1.0."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "m1", 10_000_000, t0))

    mock = MockPredictor(
        {
            "m1": [("m2", 0.6), ("m3", 0.4)],
        }
    )
    evaluator = ForecastAwareCounterfactualEvaluator(
        graph=g,
        taint_seeds=[TaintSeed("case-1", "tx-e0", 10_000_000)],
        simulation_timestamp=t0,
        predictor=mock,  # type: ignore[arg-type]
        config=ForecastGeneratorConfig(top_k=2, max_depth=1),
    )
    assert len(evaluator.scenarios) == 2
    weights = [s.normalized_weight for s in evaluator.scenarios]
    assert pytest.approx(sum(weights)) == 1.0
    assert weights[0] == pytest.approx(0.6)
    assert weights[1] == pytest.approx(0.4)


# ── 14. Probability-Weighted Metrics ─────────────────────────────────────────


def test_probability_weighted_metrics() -> None:
    """Verifies calculation of expected recovery across branches."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "m1", 10_000_000, t0))

    mock = MockPredictor(
        {
            "m1": [("m2", 0.7), ("m3", 0.3)],
            "m2": [("exit_a", 1.0)],
            "m3": [("exit_b", 1.0)],
        }
    )
    evaluator = ForecastAwareCounterfactualEvaluator(
        graph=g,
        taint_seeds=[TaintSeed("case-1", "tx-e0", 10_000_000)],
        simulation_timestamp=t0,
        predictor=mock,  # type: ignore[arg-type]
        config=ForecastGeneratorConfig(top_k=2, max_depth=2),
    )

    # An ACCOUNT_HOLD on m2 blocks branch 1 (70% probability) but not branch 2 (30% probability)
    res_m2 = evaluator.evaluate(
        InterventionCandidate(InterventionType.ACCOUNT_HOLD, target_account_id="m2"),
        simulation_timestamp=t0,
    )
    assert isinstance(res_m2, ForecastAwareCounterfactualResult)
    # Expected: 0.7 * 10,000,000 + 0.3 * 0 = 7,000,000
    assert res_m2.expected_illicit_interception == 7_000_000
    assert res_m2.worst_case_illicit_interception == 0
    assert res_m2.best_case_illicit_interception == 10_000_000
    assert res_m2.constraint_satisfaction_probability == pytest.approx(0.7)


# ── 15. Worst-Case Metrics ───────────────────────────────────────────────────


def test_worst_case_metrics() -> None:
    """Verifies worst_case_illicit_interception and worst_case_legitimate_impact."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "root", 10_000_000, t0))

    mock = MockPredictor(
        {
            "root": [("branch_a", 0.8), ("branch_b", 0.2)],
        }
    )
    evaluator = ForecastAwareCounterfactualEvaluator(
        graph=g,
        taint_seeds=[TaintSeed("case-1", "tx-e0", 10_000_000)],
        simulation_timestamp=t0,
        predictor=mock,  # type: ignore[arg-type]
        config=ForecastGeneratorConfig(top_k=2, max_depth=1),
    )

    # An ACCOUNT_HOLD on root blocks ALL branches!
    res_root = evaluator.evaluate(
        InterventionCandidate(InterventionType.ACCOUNT_HOLD, target_account_id="root"),
        simulation_timestamp=t0,
    )
    assert isinstance(res_root, ForecastAwareCounterfactualResult)
    assert res_root.worst_case_illicit_interception == 10_000_000
    assert res_root.expected_illicit_interception == 10_000_000
    assert res_root.constraint_satisfaction_probability == 1.0


# ── 16. Deterministic Repeated Runs ──────────────────────────────────────────


def test_deterministic_repeated_runs() -> None:
    """Verifies that repeated evaluations with identical inputs produce bitwise-identical results."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "m1", 8_000_000, t0))

    eval_a = ForecastAwareCounterfactualEvaluator(
        graph=g,
        taint_seeds=[TaintSeed("case-1", "tx-e0", 8_000_000)],
        simulation_timestamp=t0,
    )
    eval_b = ForecastAwareCounterfactualEvaluator(
        graph=g,
        taint_seeds=[TaintSeed("case-1", "tx-e0", 8_000_000)],
        simulation_timestamp=t0,
    )

    assert eval_a.paths == eval_b.paths
    cand = InterventionCandidate(InterventionType.ACCOUNT_HOLD, target_account_id="m1")
    res_a = eval_a.evaluate(cand, t0)
    res_b = eval_b.evaluate(cand, t0)

    assert res_a.modeled_tainted_capital_intercepted == res_b.modeled_tainted_capital_intercepted
    assert res_a.expected_illicit_interception == res_b.expected_illicit_interception
    assert res_a.worst_case_illicit_interception == res_b.worst_case_illicit_interception


# ── 17. Baseline Graph & Taint Immutability ──────────────────────────────────


def test_baseline_immutability() -> None:
    """Verifies that baseline graph and taint results remain unmutated."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "m1", 5_000_000, t0))
    initial_edge_count = g.edge_count
    initial_node_count = g.node_count

    evaluator = ForecastAwareCounterfactualEvaluator(
        graph=g,
        taint_seeds=[TaintSeed("case-1", "tx-e0", 5_000_000)],
        simulation_timestamp=t0,
    )
    evaluator.evaluate(
        InterventionCandidate(InterventionType.ACCOUNT_HOLD, target_account_id="m1"),
        simulation_timestamp=t0,
    )

    assert g.edge_count == initial_edge_count
    assert g.node_count == initial_node_count


# ── 18. Existing Optimizer Compatibility ─────────────────────────────────────


def test_existing_optimizer_compatibility() -> None:
    """Verifies that ForecastAwareCounterfactualEvaluator plugs into MultiObjectiveInterventionOptimizer."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "m1", 10_000_000, t0))

    mock = MockPredictor(
        {
            "m1": [("m2", 0.6), ("m3", 0.4)],
        }
    )
    evaluator = ForecastAwareCounterfactualEvaluator(
        graph=g,
        taint_seeds=[TaintSeed("case-1", "tx-e0", 10_000_000)],
        simulation_timestamp=t0,
        predictor=mock,  # type: ignore[arg-type]
    )

    optimizer = MultiObjectiveInterventionOptimizer(evaluator)
    candidates = evaluator.generate_candidates()
    assert len(candidates) > 0

    opt_res = optimizer.optimize(
        candidates=candidates,
        simulation_timestamp=t0,
        constraints=OptimizationConstraints(minimum_required_illicit_recovery=1_000_000),
    )
    assert isinstance(opt_res, OptimizationResult)
    assert opt_res.selected_evaluation is not None
    assert opt_res.selected_evaluation.candidate.target_account_id == "m1"
    assert opt_res.selected_evaluation.feasible is True


# ── 19. Robust Policy Selection ──────────────────────────────────────────────


def test_robust_policy_selection() -> None:
    """Verifies select_robust_intervention ranking logic."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "m1", 10_000_000, t0))

    mock = MockPredictor(
        {
            "m1": [("m2", 0.7), ("m3", 0.3)],
        }
    )
    evaluator = ForecastAwareCounterfactualEvaluator(
        graph=g,
        taint_seeds=[TaintSeed("case-1", "tx-e0", 10_000_000)],
        simulation_timestamp=t0,
        predictor=mock,  # type: ignore[arg-type]
    )

    optimizer = MultiObjectiveInterventionOptimizer(evaluator)
    candidates = evaluator.generate_candidates()
    opt_res = optimizer.optimize(candidates, t0)

    # Candidate on m1 has 100% recovery across both futures (expected 10M, worst-case 10M)
    # Candidate on m2 has 70% recovery (expected 7M, worst-case 0)
    best_robust = select_robust_intervention(opt_res.evaluations)
    assert best_robust is not None
    assert best_robust.candidate.target_account_id == "m1"


# ── 20. Forecast Benchmark Coverage ──────────────────────────────────────────


def test_forecast_benchmark_covers_10_scenarios() -> None:
    """Verifies that run_forecast_benchmark executes and covers all 10 canonical families."""
    report = run_forecast_benchmark(BenchmarkConfig(seed=42))
    assert isinstance(report, ForecastBenchmarkReport)
    assert len(report.scenarios) == 10
    assert len(report.aggregates) == 2

    # Check that both strategies were evaluated
    strategies = {agg.strategy_name for agg in report.aggregates}
    assert strategies == {"observed_world_aegis", "forecast_aware_aegis"}


# ── 21. Differing Multi-Future Recovery & Collateral (Decimal Arithmetic) ────


def test_differing_multi_future_recovery_and_collateral_exact_decimal() -> None:
    """Verifies probability-weighted expectations and worst-case metrics across differing futures.

    Future 1: Recovery = 10,000,000 paise, Collateral = 3,000,000 paise, Prob = 0.60
    Future 2: Recovery =  4,000,000 paise, Collateral = 8,000,000 paise, Prob = 0.40

    Verifies:
    - Expected Recovery = 0.60 * 10M + 0.40 * 4M = 7,600,000 paise
    - Worst-Case Recovery = min(10M, 4M) = 4,000,000 paise
    - Best-Case Recovery = max(10M, 4M) = 10,000,000 paise
    - Expected Collateral = 0.60 * 3M + 0.40 * 8M = 5,000,000 paise
    - Worst-Case Collateral = max(3M, 8M) = 8,000,000 paise
    - Best-Case Collateral = min(3M, 8M) = 3,000,000 paise
    - Metrics are computed independently from individual future evaluations and not copied.
    """
    from decimal import Decimal, ROUND_HALF_UP
    from backend.app.forecast.models import ScenarioEvaluationDetail

    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e0", "victim", "m1", 10_000_000, t0))

    # Mock predictor yielding 2 futures
    mock = MockPredictor(
        {
            "m1": [("m2", 0.60), ("m3", 0.40)],
        }
    )
    evaluator = ForecastAwareCounterfactualEvaluator(
        graph=g,
        taint_seeds=[TaintSeed("case-1", "tx-e0", 10_000_000)],
        simulation_timestamp=t0,
        predictor=mock,  # type: ignore[arg-type]
        config=ForecastGeneratorConfig(top_k=2, max_depth=1),
    )

    assert len(evaluator.scenarios) == 2
    cand = InterventionCandidate(InterventionType.ACCOUNT_HOLD, target_account_id="m1")

    # Manually build differing scenario results to verify mathematical aggregation
    res1 = CounterfactualResult(
        intervention_id="cf-01",
        intervention_type=InterventionType.ACCOUNT_HOLD,
        target_account_id="m1",
        target_event_id=None,
        simulation_timestamp=t0,
        modeled_tainted_capital_intercepted=10_000_000,
        modeled_legitimate_capital_affected=3_000_000,
        remaining_downstream_taint=0,
        number_of_affected_edges=2,
        number_of_affected_accounts=2,
        provenance_coverage=1.0,
        provenance_confidence=1.0,
        source_interception_details=(),
        explanation="",
        blocked_event_ids=(),
        affected_account_ids=(),
    )
    res2 = CounterfactualResult(
        intervention_id="cf-02",
        intervention_type=InterventionType.ACCOUNT_HOLD,
        target_account_id="m1",
        target_event_id=None,
        simulation_timestamp=t0,
        modeled_tainted_capital_intercepted=4_000_000,
        modeled_legitimate_capital_affected=8_000_000,
        remaining_downstream_taint=6_000_000,
        number_of_affected_edges=1,
        number_of_affected_accounts=1,
        provenance_coverage=1.0,
        provenance_confidence=1.0,
        source_interception_details=(),
        explanation="",
        blocked_event_ids=(),
        affected_account_ids=(),
    )

    # Mock simulator outputs
    evaluator._simulators[evaluator.scenarios[0].scenario_id].simulate = lambda c, t: res1  # type: ignore[assignment]
    evaluator._simulators[evaluator.scenarios[1].scenario_id].simulate = lambda c, t: res2  # type: ignore[assignment]

    evaluated = evaluator.evaluate(cand, t0)
    assert isinstance(evaluated, ForecastAwareCounterfactualResult)

    # 1. Decimal arithmetic verification
    w1 = Decimal("0.60")
    w2 = Decimal("0.40")
    expected_recovery_decimal = int((w1 * Decimal("10000000") + w2 * Decimal("4000000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    expected_collateral_decimal = int((w1 * Decimal("3000000") + w2 * Decimal("8000000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    assert expected_recovery_decimal == 7_600_000
    assert expected_collateral_decimal == 5_000_000

    # 2. Assert exact calculated values on the result
    assert evaluated.expected_illicit_interception == 7_600_000
    assert evaluated.worst_case_illicit_interception == 4_000_000
    assert evaluated.best_case_illicit_interception == 10_000_000

    assert evaluated.expected_legitimate_impact == 5_000_000
    assert evaluated.worst_case_legitimate_impact == 8_000_000
    assert evaluated.best_case_legitimate_impact == 3_000_000

    # 3. Assert values differ from one another and are not copies
    assert evaluated.expected_illicit_interception != evaluated.worst_case_illicit_interception
    assert evaluated.expected_illicit_interception != evaluated.best_case_illicit_interception
    assert evaluated.expected_legitimate_impact != evaluated.worst_case_legitimate_impact
    assert evaluated.expected_legitimate_impact != evaluated.best_case_legitimate_impact
    assert evaluated.expected_illicit_interception != evaluated.expected_legitimate_impact

    # 4. Assert exact integer types
    assert isinstance(evaluated.expected_illicit_interception, int)
    assert isinstance(evaluated.worst_case_illicit_interception, int)
    assert isinstance(evaluated.expected_legitimate_impact, int)
    assert isinstance(evaluated.worst_case_legitimate_impact, int)

    # 5. Assert inherited CounterfactualResult fields match robust expectations
    assert evaluated.modeled_tainted_capital_intercepted == evaluated.expected_illicit_interception
    assert evaluated.modeled_legitimate_capital_affected == evaluated.worst_case_legitimate_impact


def test_commingling_differing_future_recovery_and_collateral_simulation() -> None:
    """Verifies differing recovery and collateral in an end-to-end simulated graph.

    Account commingler receives:
    - 10,000,000 paise tainted from victim
    -  5,000,000 paise clean from customer
    Tracked total = 15,000,000 paise (2/3 tainted, 1/3 clean).

    Future 1 (prob 0.7): commingler forwards 10,000,000 to mule_a.
      Hold on mule_a blocks mule_a -> exit:
      Modeled tainted intercepted = 6,666,667 paise
      Modeled clean affected = 3,333,333 paise
    Future 2 (prob 0.3): commingler forwards 10,000,000 to mule_b (bypasses mule_a).
      Hold on mule_a blocks nothing:
      Modeled tainted intercepted = 0 paise
      Modeled clean affected = 0 paise

    Verifies probability-weighted expectation and worst-case bounding.
    """
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    # Clean inflow
    g.add_event(_make_event("e_clean", "customer", "commingler", 5_000_000, t0 - timedelta(hours=1)))
    # Tainted inflow
    g.add_event(_make_event("e_taint", "victim", "commingler", 10_000_000, t0))

    mock = MockPredictor(
        {
            "commingler": [("mule_a", 0.70), ("mule_b", 0.30)],
            "mule_a": [("exit_a", 1.0)],
            "mule_b": [("exit_b", 1.0)],
        }
    )
    evaluator = ForecastAwareCounterfactualEvaluator(
        graph=g,
        taint_seeds=[TaintSeed("case-1", "tx-e_taint", 10_000_000)],
        simulation_timestamp=t0,
        predictor=mock,  # type: ignore[arg-type]
        config=ForecastGeneratorConfig(top_k=2, max_depth=2),
    )

    cand_mule_a = InterventionCandidate(InterventionType.ACCOUNT_HOLD, target_account_id="mule_a")
    res = evaluator.evaluate(cand_mule_a, t0)
    assert isinstance(res, ForecastAwareCounterfactualResult)

    # Both recovery and collateral are >0 in Future 1 and 0 in Future 2
    assert res.worst_case_illicit_interception == 0
    assert res.best_case_illicit_interception > 0
    assert res.worst_case_legitimate_impact > 0
    assert res.best_case_legitimate_impact == 0

    assert res.expected_illicit_interception > 0
    assert res.expected_illicit_interception < res.best_case_illicit_interception
    assert res.expected_legitimate_impact > 0
    assert res.expected_legitimate_impact < res.worst_case_legitimate_impact

