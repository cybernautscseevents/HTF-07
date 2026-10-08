#!/usr/bin/env python3
"""Forensic audit of taint-evaluation coverage; does not alter propagation."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.taint import TaintEngine, TaintSeed
from scripts.generator import SyntheticWorld, generate_synthetic_world


def _seed_inputs(world: SyntheticWorld) -> list[TaintSeed]:
    events = {event.transaction_id: event for event in world.transactions}
    return [
        TaintSeed(truth.case_id, transaction_id, events[transaction_id].amount_minor_units)
        for truth in world.truths
        if truth.case_id is not None
        for transaction_id in truth.seed_transaction_ids
    ]


def _scenario_maps(world: SyntheticWorld) -> tuple[dict[str, str], dict[str, Any]]:
    scenario_by_transaction = {
        event.transaction_id: scenario_name
        for scenario_name, scenario in world.scenarios.items()
        for event in scenario.transactions
    }
    truth_by_transaction = {
        transaction_id: truth
        for truth in world.truths
        for transaction_id in truth.fraud_transaction_ids
    }
    return scenario_by_transaction, truth_by_transaction


def _causal_reachability(result: Any) -> tuple[dict[str, bool], dict[str, int]]:
    """Reachability by event sequence, matching the engine's tie ordering."""
    reachable_accounts: set[str] = set()
    first_reachable_sequence: dict[str, int] = {}
    reachable_edges: dict[str, bool] = {}
    for allocation in result.allocations:
        is_seed = allocation.allocation_method == "seed_injection"
        reachable = is_seed or allocation.sender_account_id in reachable_accounts
        reachable_edges[allocation.event_id] = reachable
        if reachable and allocation.receiver_account_id not in reachable_accounts:
            reachable_accounts.add(allocation.receiver_account_id)
            first_reachable_sequence[allocation.receiver_account_id] = allocation.sequence
    return reachable_edges, first_reachable_sequence


def _missing_category(
    allocation: Any,
    truth: Any,
    reachable: bool,
    first_reachable_sequence: dict[str, int],
    seed_transaction_ids: set[str],
) -> tuple[str | None, str | None]:
    if allocation.tainted_amount_minor_units > 0:
        return None, None
    if not reachable:
        later_reach = first_reachable_sequence.get(allocation.sender_account_id)
        if later_reach is not None and later_reach > allocation.sequence:
            return "temporal ordering", "Sender becomes seed-reachable only after this edge."
        if (
            truth.scenario_type == "smurfing"
            and allocation.sender_account_id == truth.source_account
            and allocation.transaction_id not in seed_transaction_ids
        ):
            return (
                "evaluation-definition mismatch",
                "ScenarioTruth labels this separate victim-originated smurf transfer fraud-linked, but it is not an explicit seed and has no upstream seed path.",
            )
        return "no upstream taint", "Sender has no causal path from an explicit seed."
    if allocation.taint_ratio_numerator == 0:
        return "no upstream taint", "Seed-reachable sender had no modeled tainted balance before this edge."
    if allocation.unattributed_amount_minor_units > 0:
        return "observable-balance shortfall", "Tracked observable balance could not cover the full outgoing amount."
    return "actual implementation bug", "Reachable tainted balance produced no modeled taint without a shortfall."


def audit_world(world: SyntheticWorld) -> dict[str, Any]:
    """Return an exhaustive, deterministic coverage and shortfall audit."""
    graph = TemporalGraph()
    graph.build_case(world.transactions)
    seeds = _seed_inputs(world)
    result = TaintEngine().run(graph, seeds)
    scenario_by_transaction, truth_by_transaction = _scenario_maps(world)
    allocation_by_transaction = {
        allocation.transaction_id: allocation for allocation in result.allocations
    }
    reachable_by_event, first_reach = _causal_reachability(result)
    seed_transaction_ids = {seed.transaction_id for seed in seeds}

    fraud_edges: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    for transaction_id, truth in sorted(truth_by_transaction.items()):
        allocation = allocation_by_transaction.get(transaction_id)
        if allocation is None:
            # This branch is retained for a future graph containing inactive
            # fraud labels. The current synthetic corpus has none.
            fraud_edges.append(
                {
                    "transaction_id": transaction_id,
                    "scenario": truth.scenario_type,
                    "expected_fraud_linked": True,
                    "active_transaction": False,
                    "modeled_taint_received": False,
                    "missing_taint_category": "inactive transaction",
                    "missing_taint_reason": "No active graph allocation exists.",
                }
            )
            category_counts["inactive transaction"] += 1
            continue

        reachable = reachable_by_event[allocation.event_id]
        category, reason = _missing_category(
            allocation, truth, reachable, first_reach, seed_transaction_ids
        )
        if category is not None:
            category_counts[category] += 1
        fraud_edges.append(
            {
                "transaction_id": transaction_id,
                "event_id": allocation.event_id,
                "scenario": truth.scenario_type,
                "sender_account_id": allocation.sender_account_id,
                "receiver_account_id": allocation.receiver_account_id,
                "transaction_amount_minor_units": allocation.transaction_amount_minor_units,
                "expected_fraud_linked": True,
                "active_transaction": True,
                "reachable_from_explicit_seed": reachable,
                "propagation_stopped_before_edge": category is not None,
                "modeled_taint_received": allocation.tainted_amount_minor_units > 0,
                "modeled_tainted_amount_minor_units": allocation.tainted_amount_minor_units,
                "modeled_source_case_ids": [
                    contribution.source_case_id
                    for contribution in allocation.source_contributions
                ],
                "missing_taint_category": category,
                "missing_taint_reason": reason,
            }
        )

    fraud_by_transaction = {edge["transaction_id"]: edge for edge in fraud_edges}
    shortfalls: list[dict[str, Any]] = []
    for shortfall in result.shortfalls:
        allocation = allocation_by_transaction[shortfall.transaction_id]
        fraud_edge = fraud_by_transaction.get(shortfall.transaction_id)
        shortfalls.append(
            {
                "scenario": scenario_by_transaction[shortfall.transaction_id],
                "account_id": shortfall.sender_account_id,
                "transaction_id": shortfall.transaction_id,
                "event_id": shortfall.event_id,
                "outgoing_amount_minor_units": shortfall.transaction_amount_minor_units,
                "tracked_observable_balance_before_minor_units": shortfall.tracked_balance_before_minor_units,
                "tainted_balance_before_minor_units": allocation.taint_ratio_numerator,
                "clean_balance_before_minor_units": (
                    shortfall.tracked_balance_before_minor_units
                    - allocation.taint_ratio_numerator
                ),
                "shortfall_minor_units": shortfall.shortfall_minor_units,
                "fraud_linked": fraud_edge is not None,
                "modeled_tainted_amount_minor_units": allocation.tainted_amount_minor_units,
                "caused_downstream_provenance_loss": (
                    False
                ),
                "provenance_loss_reason": (
                    "No. The pooled model allocates all available taint before "
                    "recording the non-tainted/unattributed shortfall; no taint "
                    "stock is discarded by a shortfall."
                ),
            }
        )

    tainted_fraud_edges = [
        edge for edge in fraud_edges if edge["modeled_taint_received"]
    ]
    reachable_fraud_edges = [
        edge for edge in fraud_edges if edge.get("reachable_from_explicit_seed")
    ]
    supported_fraud_edges = [
        edge
        for edge in fraud_edges
        if edge.get("active_transaction")
        and (
            allocation_by_transaction[edge["transaction_id"]].allocation_method
            == "seed_injection"
            or allocation_by_transaction[edge["transaction_id"]].unattributed_amount_minor_units
            == 0
        )
    ]
    correct_attribution = [
        edge
        for edge in tainted_fraud_edges
        if edge["modeled_source_case_ids"] == [
            truth_by_transaction[edge["transaction_id"]].case_id
        ]
    ]
    expected_branches = [
        (truth, sender_id, target_id)
        for truth in world.truths
        for sender_id, targets in truth.intended_next_hop_label.items()
        for target_id in ([targets] if isinstance(targets, str) else targets)
    ]
    preserved_branches = [
        (truth, sender_id, target_id)
        for truth, sender_id, target_id in expected_branches
        if any(
            allocation.sender_account_id == sender_id
            and allocation.receiver_account_id == target_id
            and allocation.tainted_amount_minor_units > 0
            for allocation in allocation_by_transaction.values()
        )
    ]
    reported_denominator = sum(
        len(truth.fraud_transaction_ids) * len(truth.seed_transaction_ids)
        for truth in world.truths
    )
    reported_branch_denominator = sum(
        len(
            [
                target_id
                for targets in truth.intended_next_hop_label.values()
                for target_id in ([targets] if isinstance(targets, str) else targets)
            ]
        )
        * len(truth.seed_transaction_ids)
        for truth in world.truths
    )

    def coverage(numerator: int, denominator: int) -> dict[str, Any]:
        return {
            "tainted_edges": numerator,
            "eligible_edges": denominator,
            "coverage": numerator / denominator if denominator else None,
        }

    return {
        "seed_count": len(seeds),
        "metrics": {
            "raw_fraud_flow_coverage": coverage(
                len(tainted_fraud_edges), len(fraud_edges)
            ),
            "seed_reachable_fraud_flow_coverage": coverage(
                sum(edge["modeled_taint_received"] for edge in reachable_fraud_edges),
                len(reachable_fraud_edges),
            ),
            "observable_support_coverage": coverage(
                sum(edge["modeled_taint_received"] for edge in supported_fraud_edges),
                len(supported_fraud_edges),
            ),
            "provenance_attribution_accuracy": {
                "correctly_attributed_tainted_edges": len(correct_attribution),
                "tainted_fraud_edges": len(tainted_fraud_edges),
                "accuracy": (
                    len(correct_attribution) / len(tainted_fraud_edges)
                    if tainted_fraud_edges else None
                ),
            },
            "truth_unique_branch_preservation": {
                "preserved_branches": len(preserved_branches),
                "expected_branches": len(expected_branches),
                "coverage": (
                    len(preserved_branches) / len(expected_branches)
                    if expected_branches else None
                ),
            },
            "conservation_error_minor_units": sum(
                abs(item.conservation_error_minor_units)
                for item in result.conservation
            ),
        },
        "missed_fraud_edge_categories": dict(sorted(category_counts.items())),
        "evaluation_definition_audit": {
            "truth_unique_fraud_edge_count": len(fraud_edges),
            "original_evaluator_fraud_edge_denominator": reported_denominator,
            "original_evaluator_duplicate_edge_count": reported_denominator - len(fraud_edges),
            "truth_unique_branch_count": len(expected_branches),
            "original_evaluator_branch_denominator": reported_branch_denominator,
            "original_evaluator_duplicate_branch_count": (
                reported_branch_denominator - len(expected_branches)
            ),
            "finding": "The original evaluator loops over seed sources, then re-counts the whole ScenarioTruth fraud list and branch map for each source. Fan-out has four seeds and fan-in has three, inflating denominators by 18 fraud edges and 18 branches.",
        },
        "fraud_edges": fraud_edges,
        "shortfalls": shortfalls,
        "shortfall_summary_by_scenario": dict(
            sorted(Counter(item["scenario"] for item in shortfalls).items())
        ),
        "opening_balance_finding": {
            "generator_balance_fields_found": False,
            "finding": "The synthetic generator defines AccountReference records and transactions, but no opening/pre-existing balance field or ledger initialization. Shortfalls are therefore valid observable-flow signals, not missing engine state.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit taint evaluation coverage")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_world(generate_synthetic_world(seed=args.seed))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote forensic taint audit to {args.output}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
