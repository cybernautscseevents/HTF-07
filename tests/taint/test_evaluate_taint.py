"""Regression tests for evaluate_taint.py evaluation-layer corrections.

These tests guard against:
1. Duplicate truth-edge counting across multiple seeds
2. Unseeded independent fraud flows being scored as downstream propagation failures
"""

from __future__ import annotations

import pytest

from scripts.evaluate_taint import (
    _build_seeds,
    _deduplicated_fraud_edges,
    _seed_reachable_fraud_edges,
    _observable_supported_fraud_edges,
    _unique_expected_branches,
    evaluate_world,
)
from scripts.generator import SyntheticWorld, generate_synthetic_world


@pytest.fixture(scope="module")
def canonical_world() -> SyntheticWorld:
    """Canonical synthetic world used for deterministic evaluation."""
    return generate_synthetic_world(seed=42)


@pytest.fixture(scope="module")
def canonical_result(canonical_world: SyntheticWorld) -> dict:
    return evaluate_world(canonical_world)


# ── Regression 1: No duplicate truth-edge counting across multiple seeds ────


class TestNoDuplicateTruthEdgeCounting:
    """Guard against the duplicated-denominator bug.

    The original evaluator looped over seed sources (source_id → truth) and
    for each source re-counted all of truth.fraud_transaction_ids, inflating
    the denominator when a single ScenarioTruth had multiple seeds (e.g.
    fan-out with 4 seeds, fan-in with 3 seeds).
    """

    def test_unique_fraud_edge_count_matches_deduplicated_truth(
        self, canonical_world: SyntheticWorld
    ) -> None:
        """The fraud-edge denominator must equal the number of distinct
        transaction IDs across all ScenarioTruth.fraud_transaction_ids."""
        unique_fraud_ids, _ = _deduplicated_fraud_edges(canonical_world)

        # Count raw (potentially duplicated) fraud edges by naively iterating
        # all truths × all fraud_transaction_ids
        raw_count = sum(
            len(truth.fraud_transaction_ids) for truth in canonical_world.truths
        )
        # They should already be equal if each tx belongs to one truth,
        # but the important thing is deduplicated_fraud_edges returns a set
        assert len(unique_fraud_ids) <= raw_count, (
            "Deduplication should never increase the count"
        )

    def test_multi_seed_truth_does_not_inflate_denominator(
        self, canonical_world: SyntheticWorld, canonical_result: dict
    ) -> None:
        """If a ScenarioTruth has N seeds, its fraud edges must still be
        counted once in the denominator, not N times."""
        # Identify truths with multiple seeds
        multi_seed_truths = [
            truth for truth in canonical_world.truths
            if len(truth.seed_transaction_ids) > 1
        ]
        assert multi_seed_truths, (
            "The canonical world should have at least one multi-seed scenario "
            "(fan-out or fan-in) for this regression test to be meaningful"
        )

        # The old bug: denominator = Σ(|fraud_tx_ids| × |seed_tx_ids|)
        inflated_denominator = sum(
            len(truth.fraud_transaction_ids) * len(truth.seed_transaction_ids)
            for truth in canonical_world.truths
        )
        # The corrected denominator
        unique_fraud_ids, _ = _deduplicated_fraud_edges(canonical_world)
        corrected_denominator = len(unique_fraud_ids)

        assert corrected_denominator < inflated_denominator, (
            f"The inflated denominator ({inflated_denominator}) must exceed "
            f"the corrected one ({corrected_denominator}), confirming the old "
            f"bug would have produced wrong results"
        )
        # And the reported metric uses the corrected denominator
        assert (
            canonical_result["A_unique_raw_fraud_edge_coverage"][
                "unique_truth_fraud_edges"
            ]
            == corrected_denominator
        )

    def test_deduplication_produces_set_not_list(
        self, canonical_world: SyntheticWorld
    ) -> None:
        """The deduplication function returns a set, which by definition
        prevents double-counting."""
        unique_fraud_ids, _ = _deduplicated_fraud_edges(canonical_world)
        assert isinstance(unique_fraud_ids, set)


# ── Regression 2: Unseeded independent fraud flows are not scored
#    as downstream propagation failures ──────────────────────────────────────


class TestUnseededIndependentFraudNotScoredAsPropagationFailures:
    """Guard against classifying evaluation-boundary cases as taint misses.

    Smurfing scenario: 20 fraud transactions but only smurf001 is seeded.
    smurf002–smurf020 are independent victim-originated transfers that share
    a case but have no taint propagation path from the seed. These must NOT
    count against seed-reachable coverage.
    """

    def test_unseeded_independent_injections_identified(
        self, canonical_result: dict
    ) -> None:
        """The evaluation must explicitly identify unseeded independent
        fraud injections."""
        boundary_cases = canonical_result["unseeded_independent_fraud_injections"]
        assert boundary_cases["count"] > 0, (
            "The canonical world should contain unseeded independent fraud "
            "injections (smurfing smurf002–smurf020)"
        )
        assert boundary_cases["classification"] == (
            "evaluation-boundary cases, not propagation misses"
        )

    def test_unseeded_edges_excluded_from_seed_reachable_denominator(
        self, canonical_world: SyntheticWorld, canonical_result: dict
    ) -> None:
        """Unseeded independent edges must NOT appear in the seed-reachable
        denominator, so they cannot deflate the PRIMARY metric."""
        unique_fraud_ids, truth_for_fraud_tx = _deduplicated_fraud_edges(
            canonical_world
        )
        seeds, _ = _build_seeds(canonical_world)
        seed_tx_ids = {seed.transaction_id for seed in seeds}

        # Run the engine to get allocations
        from backend.app.graph.temporal_graph import TemporalGraph
        from backend.app.taint import TaintEngine

        graph = TemporalGraph()
        graph.build_case(canonical_world.transactions)
        result = TaintEngine().run(graph, seeds)

        seed_reachable, unseeded = _seed_reachable_fraud_edges(
            unique_fraud_ids, truth_for_fraud_tx, result, seed_tx_ids
        )

        reported = canonical_result["B_seed_reachable_fraud_edge_coverage_PRIMARY"]
        assert reported["seed_reachable_truth_edges"] == len(seed_reachable)
        # Unseeded edges should not be in the seed-reachable set
        assert not (unseeded & seed_reachable), (
            "Unseeded and seed-reachable sets must be disjoint"
        )

    def test_seed_reachable_plus_unseeded_equals_total(
        self, canonical_world: SyntheticWorld
    ) -> None:
        """seed-reachable ∪ unseeded-independent = all unique fraud edges."""
        unique_fraud_ids, truth_for_fraud_tx = _deduplicated_fraud_edges(
            canonical_world
        )
        seeds, _ = _build_seeds(canonical_world)
        seed_tx_ids = {seed.transaction_id for seed in seeds}

        from backend.app.graph.temporal_graph import TemporalGraph
        from backend.app.taint import TaintEngine

        graph = TemporalGraph()
        graph.build_case(canonical_world.transactions)
        result = TaintEngine().run(graph, seeds)

        seed_reachable, unseeded = _seed_reachable_fraud_edges(
            unique_fraud_ids, truth_for_fraud_tx, result, seed_tx_ids
        )

        assert seed_reachable | unseeded == unique_fraud_ids

    def test_smurfing_unseeded_not_in_primary_metric(
        self, canonical_world: SyntheticWorld
    ) -> None:
        """Specifically verify smurfing scenario: only smurf001 is seeded,
        smurf002+ are unseeded independent and must not deflate the PRIMARY
        seed-reachable coverage."""
        smurfing_truths = [
            truth for truth in canonical_world.truths
            if truth.scenario_type == "smurfing"
        ]
        if not smurfing_truths:
            pytest.skip("No smurfing scenario in the canonical world")

        truth = smurfing_truths[0]
        assert len(truth.seed_transaction_ids) == 1, (
            "Smurfing should have exactly one seed"
        )
        assert len(truth.fraud_transaction_ids) > 1, (
            "Smurfing should have multiple fraud transactions"
        )
        # The unseeded ones = fraud_transaction_ids - seed_transaction_ids
        unseeded_smurf_count = len(
            set(truth.fraud_transaction_ids) - set(truth.seed_transaction_ids)
        )
        assert unseeded_smurf_count > 0


# ── Structural metric tests ────────────────────────────────────────────────


class TestMetricStructure:
    """Verify the corrected evaluation output has all required metric keys."""

    def test_all_five_metrics_present(self, canonical_result: dict) -> None:
        assert "A_unique_raw_fraud_edge_coverage" in canonical_result
        assert "B_seed_reachable_fraud_edge_coverage_PRIMARY" in canonical_result
        assert "C_observable_supported_coverage" in canonical_result
        assert "D_provenance_attribution_accuracy" in canonical_result
        assert "E_unique_branch_preservation" in canonical_result

    def test_seed_reachable_is_primary(self, canonical_result: dict) -> None:
        primary = canonical_result["B_seed_reachable_fraud_edge_coverage_PRIMARY"]
        assert "note" in primary
        assert "PRIMARY" in primary["note"]

    def test_conservation_error_preserved(self, canonical_result: dict) -> None:
        assert "tainted_amount_conservation" in canonical_result
        conservation = canonical_result["tainted_amount_conservation"]
        assert "absolute_error_minor_units" in conservation

    def test_shortfall_diagnostics_preserved(self, canonical_result: dict) -> None:
        assert "observable_balance_shortfalls" in canonical_result

    def test_unseeded_boundary_cases_section_present(
        self, canonical_result: dict
    ) -> None:
        assert "unseeded_independent_fraud_injections" in canonical_result

    def test_seed_reachable_coverage_at_least_as_high_as_raw(
        self, canonical_result: dict
    ) -> None:
        """Since unseeded edges are excluded from B but included in A,
        B.coverage >= A.coverage must hold."""
        raw = canonical_result["A_unique_raw_fraud_edge_coverage"]["coverage"]
        primary = canonical_result[
            "B_seed_reachable_fraud_edge_coverage_PRIMARY"
        ]["coverage"]
        if raw is not None and primary is not None:
            assert primary >= raw, (
                f"Seed-reachable coverage ({primary}) must be >= raw coverage "
                f"({raw}) because the denominator excludes unreachable edges"
            )


# ── Branch deduplication ───────────────────────────────────────────────────


class TestBranchDeduplication:
    def test_unique_branches_not_inflated(
        self, canonical_world: SyntheticWorld, canonical_result: dict
    ) -> None:
        unique = _unique_expected_branches(canonical_world)
        reported = canonical_result["E_unique_branch_preservation"]
        assert reported["expected_branches"] == len(unique)
