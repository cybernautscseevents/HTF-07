"""
AEGIS-Flow Synthetic Generator Package
======================================

Deterministic generator for synthetic financial transactions and fraud scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from contracts.account import AccountReference
from contracts.case import FraudCase
from contracts.transaction import TransactionEvent
from scripts.generator.accounts import AccountPool, AccountRole, SYNTHETIC_BANKS, create_account
from scripts.generator.scenarios import (
    SCENARIO_GENERATORS,
    ScenarioResult,
    generate_benign_high_volume_merchant_scenario,
    generate_cold_start_scenario,
    generate_commingling_scenario,
    generate_cross_bank_scenario,
    generate_fan_in_scenario,
    generate_fan_out_fan_in_scenario,
    generate_fan_out_scenario,
    generate_rapid_pass_through_scenario,
    generate_simple_chain_scenario,
    generate_smurfing_scenario,
)
from scripts.generator.truth import ScenarioTruth

UTC = timezone.utc


@dataclass(frozen=True)
class SyntheticWorld:
    """Consolidated representation of all generated scenarios in a synthetic world."""

    transactions: list[TransactionEvent]
    cases: list[FraudCase]
    truths: list[ScenarioTruth]
    accounts: list[AccountReference]
    scenarios: dict[str, ScenarioResult]


def generate_synthetic_world(
    seed: int = 42,
    base_time: datetime | None = None,
    scenario_families: Sequence[str] | None = None,
) -> SyntheticWorld:
    """Generate a complete synthetic financial world across scenario families.

    Guarantees strict determinism: same seed produces identical results.
    """
    ref_time = base_time or datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC)
    families = scenario_families or list(SCENARIO_GENERATORS.keys())

    all_txns: list[TransactionEvent] = []
    all_cases: list[FraudCase] = []
    all_truths: list[ScenarioTruth] = []
    all_accounts_dict: dict[str, AccountReference] = {}
    scenario_map: dict[str, ScenarioResult] = {}

    for idx, fam_name in enumerate(families):
        if fam_name not in SCENARIO_GENERATORS:
            raise ValueError(f"Unknown scenario family: '{fam_name}'. Available: {list(SCENARIO_GENERATORS.keys())}")

        gen_func = SCENARIO_GENERATORS[fam_name]
        scenario_id = f"sc-{idx+1:02d}-{fam_name.replace('_', '-')}"
        scenario_seed = seed + (idx * 1007)

        result = gen_func(
            scenario_id=scenario_id,
            seed=scenario_seed,
            base_time=ref_time,
        )

        scenario_map[fam_name] = result
        all_txns.extend(result.transactions)
        all_cases.extend(result.cases)
        all_truths.append(result.truth)
        for acct in result.accounts:
            all_accounts_dict[acct.account_id] = acct

    # Sort all transactions deterministically by occurred_at then event_id
    all_txns.sort(key=lambda t: (t.occurred_at, t.event_id))

    return SyntheticWorld(
        transactions=all_txns,
        cases=all_cases,
        truths=all_truths,
        accounts=list(all_accounts_dict.values()),
        scenarios=scenario_map,
    )


__all__ = [
    # Synthetic banks
    "SYNTHETIC_BANKS",
    "AccountRole",
    "create_account",
    "AccountPool",
    # Ground truth
    "ScenarioTruth",
    # Scenarios
    "ScenarioResult",
    "SCENARIO_GENERATORS",
    "generate_simple_chain_scenario",
    "generate_fan_out_scenario",
    "generate_fan_in_scenario",
    "generate_fan_out_fan_in_scenario",
    "generate_commingling_scenario",
    "generate_cold_start_scenario",
    "generate_cross_bank_scenario",
    "generate_smurfing_scenario",
    "generate_rapid_pass_through_scenario",
    "generate_benign_high_volume_merchant_scenario",
    # World builder
    "SyntheticWorld",
    "generate_synthetic_world",
]
