#!/usr/bin/env python3
"""
AEGIS-Flow Synthetic World Generator CLI
=========================================

Generates deterministic synthetic transaction streams and ground-truth metadata
for demonstrating AEGIS-Flow, testing graph behavior, verifying taint propagation,
and benchmarking ML models.

Usage:
    python scripts/generate_synthetic.py [--seed 42] [--output-dir data/synthetic]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from datetime import datetime, timezone
from typing import Any

from scripts.generator import (
    SCENARIO_GENERATORS,
    SyntheticWorld,
    generate_synthetic_world,
)

UTC = timezone.utc


def serialize_models(models: list[Any]) -> list[dict[str, Any]]:
    """Serialize Pydantic models to JSON-compatible dictionaries."""
    return [m.model_dump(mode="json") for m in models]


def compute_world_summary(world: SyntheticWorld, seed: int) -> dict[str, Any]:
    """Compute aggregate statistical metrics across the generated synthetic world.

    Explicitly distinguishes between:
    - Injected Fraud Capital: the original illicit principal injected into the scenario/network.
    - Fraud-Linked Edge Volume: cumulative sum of amounts across transaction edges labeled as fraud-linked.
      Fraud-Linked Edge Volume can exceed Injected Fraud Capital when the same capital traverses multiple transaction edges.
      It must not be interpreted as unique stolen capital.
    - Legitimate Transaction Volume: genuine background, decoy, historical, and merchant volumes.
    - Total Transaction Volume: sum of all transaction amounts across the entire network.
    """
    total_txns = len(world.transactions)
    total_volume_paise = sum(t.amount_minor_units for t in world.transactions)

    # Injected Fraud Capital: unique original illicit capital injected across all scenarios
    injected_fraud_capital_paise = sum(truth.injected_fraud_amount for truth in world.truths)

    fraud_txn_ids: set[str] = set()
    for truth in world.truths:
        fraud_txn_ids.update(truth.fraud_transaction_ids)

    fraud_edge_txns = [t for t in world.transactions if t.transaction_id in fraud_txn_ids]
    legit_txns = [t for t in world.transactions if t.transaction_id not in fraud_txn_ids]

    fraud_linked_edge_volume_paise = sum(t.amount_minor_units for t in fraud_edge_txns)
    legitimate_transaction_volume_paise = sum(t.amount_minor_units for t in legit_txns)

    # Institution breakdown
    institutions: dict[str, int] = {}
    for t in world.transactions:
        for bank in [t.sender.institution, t.receiver.institution]:
            if bank:
                institutions[bank] = institutions.get(bank, 0) + 1

    # Scenario details
    scenario_stats = []
    for s_name, s_res in world.scenarios.items():
        s_fraud_edge_txns = [
            t for t in s_res.transactions if t.transaction_id in s_res.truth.fraud_transaction_ids
        ]
        s_fraud_edge_volume = sum(t.amount_minor_units for t in s_fraud_edge_txns)
        scenario_stats.append({
            "scenario_id": s_res.scenario_id,
            "scenario_type": s_res.scenario_type,
            "transaction_count": len(s_res.transactions),
            "case_count": len(s_res.cases),
            "injected_fraud_capital_paise": s_res.truth.injected_fraud_amount,
            "injected_fraud_capital_inr": f"₹{s_res.truth.injected_fraud_amount / 100:,.2f}",
            "fraud_linked_edges_count": len(s_fraud_edge_txns),
            "fraud_linked_edge_volume_paise": s_fraud_edge_volume,
            "fraud_linked_edge_volume_inr": f"₹{s_fraud_edge_volume / 100:,.2f}",
            "fraud_accounts_count": len(s_res.truth.fraud_accounts),
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "scenarios_count": len(world.scenarios),
        "total_accounts": len(world.accounts),
        "total_cases": len(world.cases),
        "total_transactions": total_txns,
        "total_transaction_volume_paise": total_volume_paise,
        "total_transaction_volume_inr": f"₹{total_volume_paise / 100:,.2f}",
        "injected_fraud_capital_paise": injected_fraud_capital_paise,
        "injected_fraud_capital_inr": f"₹{injected_fraud_capital_paise / 100:,.2f}",
        "fraud_linked_edges_count": len(fraud_edge_txns),
        "fraud_linked_edge_volume_paise": fraud_linked_edge_volume_paise,
        "fraud_linked_edge_volume_inr": f"₹{fraud_linked_edge_volume_paise / 100:,.2f}",
        "legitimate_transactions_count": len(legit_txns),
        "legitimate_transaction_volume_paise": legitimate_transaction_volume_paise,
        "legitimate_transaction_volume_inr": f"₹{legitimate_transaction_volume_paise / 100:,.2f}",
        "institution_participation": institutions,
        "scenarios": scenario_stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AEGIS-Flow Deterministic Synthetic World Generator"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic generation (default: 42)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/synthetic"),
        help="Directory where JSON artifacts will be written (default: data/synthetic)",
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        default="all",
        help="Comma-separated list of scenario families or 'all'",
    )
    args = parser.parse_args()

    selected_scenarios = None
    if args.scenarios != "all":
        selected_scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]

    print(f"Generating AEGIS-Flow synthetic world (seed={args.seed})...")
    world = generate_synthetic_world(
        seed=args.seed,
        scenario_families=selected_scenarios,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Transactions
    txns_path = args.output_dir / "transactions.json"
    with open(txns_path, "w", encoding="utf-8") as f:
        json.dump(serialize_models(world.transactions), f, indent=2)
    print(f"  ✓ Wrote {len(world.transactions)} transactions to {txns_path}")

    # 2. Fraud cases
    cases_path = args.output_dir / "cases.json"
    with open(cases_path, "w", encoding="utf-8") as f:
        json.dump(serialize_models(world.cases), f, indent=2)
    print(f"  ✓ Wrote {len(world.cases)} fraud cases to {cases_path}")

    # 3. Ground truth metadata
    truth_path = args.output_dir / "ground_truth.json"
    with open(truth_path, "w", encoding="utf-8") as f:
        json.dump(serialize_models(world.truths), f, indent=2)
    print(f"  ✓ Wrote {len(world.truths)} scenario truths to {truth_path}")

    # 4. Summary metrics
    summary = compute_world_summary(world, seed=args.seed)
    summary_path = args.output_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"  ✓ Wrote scenario summary to {summary_path}")

    print("\n--- Synthetic World Summary ---")
    print(f"Total Transactions             : {summary['total_transactions']}")
    print(f"Total Cases                    : {summary['total_cases']}")
    print(f"Total Accounts                 : {summary['total_accounts']}")
    print(f"Total Transaction Volume (INR) : {summary['total_transaction_volume_inr']}")
    print(f"Injected Fraud Capital (INR)   : {summary['injected_fraud_capital_inr']}")
    print(f"Fraud-Linked Edge Volume (INR) : {summary['fraud_linked_edge_volume_inr']} ({summary['fraud_linked_edges_count']} edges)")
    print(f"Legit Transaction Volume (INR) : {summary['legitimate_transaction_volume_inr']} ({summary['legitimate_transactions_count']} txns)")
    print(f"Institutions                   : {list(summary['institution_participation'].keys())}")
    print("\nNote: Fraud-Linked Edge Volume can exceed Injected Fraud Capital when the same capital")
    print("      traverses multiple transaction edges. It must not be interpreted as unique stolen capital.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
