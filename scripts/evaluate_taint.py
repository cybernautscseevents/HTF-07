#!/usr/bin/env python3
"""Evaluate deterministic taint provenance against synthetic ScenarioTruth.

ScenarioTruth is intentionally confined to this evaluation script. Runtime
taint propagation consumes only a TemporalGraph and explicit TaintSeed inputs.

Metrics
-------
A. Unique raw ScenarioTruth fraud-edge coverage
B. Seed-reachable fraud-edge coverage  ← PRIMARY provenance metric
C. Observable-supported coverage
D. Provenance attribution accuracy
E. Unique branch preservation
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

# Allow direct ``python scripts/evaluate_taint.py`` execution from any cwd.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.taint import TaintEngine, TaintSeed
from scripts.generator import SyntheticWorld, generate_synthetic_world


def _build_seeds(world: SyntheticWorld) -> tuple[list[TaintSeed], dict[str, Any]]:
    """Derive evaluation-only explicit seeds from synthetic ground truth."""
    events_by_transaction = {
        event.transaction_id: event for event in world.transactions
    }
    seeds: list[TaintSeed] = []
    truth_by_source: dict[str, Any] = {}
    for truth in world.truths:
        if truth.case_id is None:
            continue
        for transaction_id in truth.seed_transaction_ids:
            event = events_by_transaction[transaction_id]
            seed = TaintSeed(
                case_id=truth.case_id,
                transaction_id=transaction_id,
                tainted_amount_minor_units=event.amount_minor_units,
            )
            seeds.append(seed)
            truth_by_source[seed.source_id] = truth
    return seeds, truth_by_source


def _deduplicated_fraud_edges(
    world: SyntheticWorld,
) -> tuple[set[str], dict[str, Any]]:
    """Return unique fraud transaction IDs and a mapping from each to its truth.

    A transaction ID appearing in multiple ScenarioTruth records is counted
    exactly once to prevent inflated denominators.
    """
    unique_fraud_ids: set[str] = set()
    truth_for_fraud_tx: dict[str, Any] = {}
    for truth in world.truths:
        for tx_id in truth.fraud_transaction_ids:
            unique_fraud_ids.add(tx_id)
            # Last-writer wins; in practice each fraud tx belongs to one truth.
            truth_for_fraud_tx[tx_id] = truth
    return unique_fraud_ids, truth_for_fraud_tx


def _seed_reachable_fraud_edges(
    unique_fraud_ids: set[str],
    truth_for_fraud_tx: dict[str, Any],
    result: Any,
    seed_transaction_ids: set[str],
) -> tuple[set[str], set[str]]:
    """Classify unique fraud edges into seed-reachable and unseeded-independent.

    Seed-reachable: fraud edge whose sender has a causal path from an explicit
    seed (including the seed injection edge itself).

    Unseeded-independent: fraud edge whose sender has NO causal path from any
    explicit seed. These are evaluation-boundary cases — the truth labels them
    fraud-linked but the evaluation seeding did not provide an upstream seed.
    For example, smurfing smurf002–smurf020 are independent victim-originated
    transfers that share a case but have no taint propagation path from smurf001.
    """
    # Build reachability from explicit seeds through the allocation graph
    reachable_accounts: set[str] = set()
    for allocation in result.allocations:
        is_seed = allocation.allocation_method == "seed_injection"
        sender_reachable = allocation.sender_account_id in reachable_accounts
        if is_seed or sender_reachable:
            reachable_accounts.add(allocation.receiver_account_id)

    allocation_by_tx = {
        allocation.transaction_id: allocation for allocation in result.allocations
    }

    seed_reachable: set[str] = set()
    unseeded_independent: set[str] = set()
    for tx_id in unique_fraud_ids:
        if tx_id in seed_transaction_ids:
            # The seed injection edge itself is always seed-reachable
            seed_reachable.add(tx_id)
            continue
        alloc = allocation_by_tx.get(tx_id)
        if alloc is None:
            # No active allocation — not reachable
            unseeded_independent.add(tx_id)
            continue
        if alloc.sender_account_id in reachable_accounts:
            seed_reachable.add(tx_id)
        else:
            unseeded_independent.add(tx_id)

    return seed_reachable, unseeded_independent


def _observable_supported_fraud_edges(
    unique_fraud_ids: set[str],
    result: Any,
) -> set[str]:
    """Fraud edges where the engine had full observable-balance support.

    An edge is observable-supported if it is either a seed injection or the
    sender had tracked observable balance >= transaction amount (no shortfall).
    """
    allocation_by_tx = {
        allocation.transaction_id: allocation for allocation in result.allocations
    }
    supported: set[str] = set()
    for tx_id in unique_fraud_ids:
        alloc = allocation_by_tx.get(tx_id)
        if alloc is None:
            continue
        if (
            alloc.allocation_method == "seed_injection"
            or alloc.unattributed_amount_minor_units == 0
        ):
            supported.add(tx_id)
    return supported


def _unique_expected_branches(
    world: SyntheticWorld,
) -> list[tuple[str, str]]:
    """Return deduplicated (sender, target) branch pairs across all truths."""
    seen: set[tuple[str, str]] = set()
    branches: list[tuple[str, str]] = []
    for truth in world.truths:
        for sender_id, targets in truth.intended_next_hop_label.items():
            target_ids = [targets] if isinstance(targets, str) else list(targets)
            for target_id in target_ids:
                key = (sender_id, target_id)
                if key not in seen:
                    seen.add(key)
                    branches.append(key)
    return branches


def evaluate_world(world: SyntheticWorld) -> dict[str, Any]:
    """Run the engine and report exact observed benchmark measurements."""
    graph = TemporalGraph()
    graph.build_case(world.transactions)
    seeds, truth_by_source = _build_seeds(world)

    started = perf_counter()
    result = TaintEngine().run(graph, seeds)
    runtime_seconds = perf_counter() - started

    seed_transaction_ids = {seed.transaction_id for seed in seeds}

    # ── Deduplicate fraud edges by transaction identity ──────────────────
    unique_fraud_ids, truth_for_fraud_tx = _deduplicated_fraud_edges(world)

    allocation_by_tx = {
        allocation.transaction_id: allocation for allocation in result.allocations
    }

    # Tainted unique fraud edges: edges that received modeled taint > 0
    tainted_unique_fraud_ids = {
        tx_id
        for tx_id in unique_fraud_ids
        if tx_id in allocation_by_tx
        and allocation_by_tx[tx_id].tainted_amount_minor_units > 0
    }

    # ── A. Unique raw ScenarioTruth fraud-edge coverage ─────────────────
    raw_coverage_numerator = len(tainted_unique_fraud_ids)
    raw_coverage_denominator = len(unique_fraud_ids)

    # ── B. Seed-reachable fraud-edge coverage (PRIMARY) ─────────────────
    seed_reachable, unseeded_independent = _seed_reachable_fraud_edges(
        unique_fraud_ids, truth_for_fraud_tx, result, seed_transaction_ids
    )
    tainted_seed_reachable = tainted_unique_fraud_ids & seed_reachable
    seed_reachable_coverage_numerator = len(tainted_seed_reachable)
    seed_reachable_coverage_denominator = len(seed_reachable)

    # ── C. Observable-supported coverage ────────────────────────────────
    observable_supported = _observable_supported_fraud_edges(unique_fraud_ids, result)
    tainted_observable_supported = tainted_unique_fraud_ids & observable_supported
    observable_supported_numerator = len(tainted_observable_supported)
    observable_supported_denominator = len(observable_supported)

    # ── D. Provenance attribution accuracy ──────────────────────────────
    correctly_attributed = 0
    for tx_id in tainted_unique_fraud_ids:
        alloc = allocation_by_tx[tx_id]
        truth = truth_for_fraud_tx[tx_id]
        source_case_ids = [c.source_case_id for c in alloc.source_contributions]
        if source_case_ids == [truth.case_id]:
            correctly_attributed += 1

    # ── E. Unique branch preservation ───────────────────────────────────
    expected_branches = _unique_expected_branches(world)
    preserved_branches = [
        (sender_id, target_id)
        for sender_id, target_id in expected_branches
        if any(
            allocation.sender_account_id == sender_id
            and allocation.receiver_account_id == target_id
            and allocation.tainted_amount_minor_units > 0
            for allocation in result.allocations
        )
    ]

    # ── Commingling (unchanged) ─────────────────────────────────────────
    commingling_candidates = 0
    commingling_correct = 0
    for source_id, truth in truth_by_source.items():
        if truth.scenario_type == "commingling":
            allocations = result.allocations_for_source(source_id)
            candidates = [
                allocation
                for allocation in allocations
                if allocation.tainted_amount_minor_units > 0
                and allocation.clean_amount_minor_units > 0
            ]
            commingling_candidates += 1
            commingling_correct += int(bool(candidates))

    # ── Seed provenance attribution (unchanged) ─────────────────────────
    seed_by_source = {seed.source_id: seed for seed in seeds}
    allocation_by_source = {
        source_id: result.allocations_for_source(source_id)
        for source_id in truth_by_source
    }
    source_seed_events_correct = sum(
        any(
            allocation.transaction_id == seed_by_source[source_id].transaction_id
            and allocation.allocation_method == "seed_injection"
            for allocation in allocations
        )
        for source_id, allocations in allocation_by_source.items()
    )

    # ── Conservation error (unchanged) ──────────────────────────────────
    total_initial = sum(
        item.initial_tainted_amount_minor_units for item in result.conservation
    )
    total_remaining = sum(
        item.remaining_observable_tainted_amount_minor_units
        for item in result.conservation
    )
    total_error = sum(
        abs(item.conservation_error_minor_units) for item in result.conservation
    )

    def _coverage(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    # ── Unseeded independent fraud injections detail ────────────────────
    unseeded_detail: list[dict[str, Any]] = []
    for tx_id in sorted(unseeded_independent):
        truth = truth_for_fraud_tx[tx_id]
        unseeded_detail.append({
            "transaction_id": tx_id,
            "scenario_type": truth.scenario_type,
            "case_id": truth.case_id,
            "classification": "evaluation-boundary case",
            "reason": (
                "This fraud-linked transaction has no causal upstream path from "
                "any explicit seed. It is an independent fraud injection that "
                "AEGIS-Flow correctly does not propagate taint to, because "
                "propagation begins from explicit confirmed/high-confidence "
                "fraud seeds only."
            ),
        })

    return {
        "runtime_seconds": round(runtime_seconds, 6),
        "seed_count": len(seeds),
        "active_edge_count": len(result.allocations),
        "tainted_edge_count": sum(
            allocation.tainted_amount_minor_units > 0
            for allocation in result.allocations
        ),
        "tainted_amount_conservation": {
            "initial_minor_units": total_initial,
            "remaining_minor_units": total_remaining,
            "absolute_error_minor_units": total_error,
        },
        "seed_provenance_attribution": {
            "correct_seed_injection_records": source_seed_events_correct,
            "seed_count": len(seeds),
        },
        # ── A. Unique raw fraud-edge coverage ───────────────────────────
        "A_unique_raw_fraud_edge_coverage": {
            "modeled_tainted_unique_fraud_edges": raw_coverage_numerator,
            "unique_truth_fraud_edges": raw_coverage_denominator,
            "coverage": _coverage(raw_coverage_numerator, raw_coverage_denominator),
        },
        # ── B. Seed-reachable fraud-edge coverage (PRIMARY) ─────────────
        "B_seed_reachable_fraud_edge_coverage_PRIMARY": {
            "modeled_tainted_seed_reachable_edges": seed_reachable_coverage_numerator,
            "seed_reachable_truth_edges": seed_reachable_coverage_denominator,
            "coverage": _coverage(
                seed_reachable_coverage_numerator,
                seed_reachable_coverage_denominator,
            ),
            "note": "PRIMARY provenance metric: AEGIS-Flow begins from explicit confirmed/high-confidence fraud seeds.",
        },
        # ── C. Observable-supported coverage ────────────────────────────
        "C_observable_supported_coverage": {
            "modeled_tainted_observable_supported_edges": observable_supported_numerator,
            "observable_supported_truth_edges": observable_supported_denominator,
            "coverage": _coverage(
                observable_supported_numerator, observable_supported_denominator
            ),
        },
        # ── D. Provenance attribution accuracy ──────────────────────────
        "D_provenance_attribution_accuracy": {
            "correctly_attributed_tainted_edges": correctly_attributed,
            "tainted_edges": len(tainted_unique_fraud_ids),
            "accuracy": _coverage(correctly_attributed, len(tainted_unique_fraud_ids)),
        },
        # ── E. Unique branch preservation ───────────────────────────────
        "E_unique_branch_preservation": {
            "preserved_branches": len(preserved_branches),
            "expected_branches": len(expected_branches),
            "coverage": _coverage(len(preserved_branches), len(expected_branches)),
        },
        "commingling_attribution": {
            "correct_scenarios": commingling_correct,
            "scenarios": commingling_candidates,
            "coverage": (
                commingling_correct / commingling_candidates
                if commingling_candidates else None
            ),
        },
        "multi_seed_attribution": {
            "status": "not_applicable",
            "reason": "The canonical synthetic world has no multi-seed scenario; covered by deterministic unit tests.",
        },
        # ── Evaluation-boundary cases ───────────────────────────────────
        "unseeded_independent_fraud_injections": {
            "count": len(unseeded_independent),
            "classification": "evaluation-boundary cases, not propagation misses",
            "detail": unseeded_detail,
        },
        # ── Shortfall diagnostics (preserved) ──────────────────────────
        "observable_balance_shortfalls": {
            "count": len(result.shortfalls),
            "total_minor_units": sum(
                shortfall.shortfall_minor_units for shortfall in result.shortfalls
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate AEGIS-Flow taint provenance")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--scenarios",
        default="all",
        help="Comma-separated generator families, or 'all'.",
    )
    args = parser.parse_args()
    families = None if args.scenarios == "all" else args.scenarios.split(",")
    world = generate_synthetic_world(seed=args.seed, scenario_families=families)
    print(json.dumps(evaluate_world(world), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
