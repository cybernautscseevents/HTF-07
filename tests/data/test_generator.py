"""
Tests for AEGIS-Flow Synthetic Generator
=========================================

Verifies:
1. Deterministic generation (same seed -> bit-for-bit identical world)
2. Valid canonical events (contracts schema conformance, round-trip serialization)
3. Scenario topology (linear chains, fan-out, fan-in, diamond/chokepoints)
4. Known fraud labels (ground-truth isolation, completeness)
5. Cold-start accounts have no historical events before fraud seed
6. Cross-bank events traverse multiple synthetic institutions (BANK_A - BANK_D)
7. Smurfing generates deliberately small micro-transactions below benchmark threshold
8. Commingling contains both legitimate and illicit inflows
9. Rapid pass-through exhibits sub-minute inter-hop dwell times
10. Benign merchant produces high-volume clean transactions without false fraud labels
11. Injected fraud capital vs. fraud-linked edge volume semantic distinction
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from contracts.account import AccountReference
from contracts.case import FraudCase
from contracts.enums import EventOrigin, TransactionChannel, TransactionStatus
from contracts.transaction import TransactionEvent
from scripts.generate_synthetic import compute_world_summary
from scripts.generator import (
    SYNTHETIC_BANKS,
    ScenarioTruth,
    SyntheticWorld,
    generate_synthetic_world,
)
from scripts.generator.scenarios import (
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

UTC = timezone.utc


# ── 1. Deterministic Generation ───────────────────────────────────────────────


class TestDeterminism:
    def test_same_seed_identical_world(self):
        """Verifies that running with identical seed produces bit-for-bit identical outputs."""
        world_a = generate_synthetic_world(seed=42)
        world_b = generate_synthetic_world(seed=42)

        assert len(world_a.transactions) == len(world_b.transactions)
        assert len(world_a.cases) == len(world_b.cases)
        assert len(world_a.truths) == len(world_b.truths)
        assert len(world_a.accounts) == len(world_b.accounts)

        # Compare transactions
        for ta, tb in zip(world_a.transactions, world_b.transactions):
            assert ta.event_id == tb.event_id
            assert ta.transaction_id == tb.transaction_id
            assert ta.amount_minor_units == tb.amount_minor_units
            assert ta.occurred_at == tb.occurred_at
            assert ta.observed_at == tb.observed_at
            assert ta.sender == tb.sender
            assert ta.receiver == tb.receiver
            assert ta.channel == tb.channel

        # Compare fraud cases
        for ca, cb in zip(world_a.cases, world_b.cases):
            assert ca.case_id == cb.case_id
            assert ca.transaction_ids == cb.transaction_ids
            assert ca.opened_at == cb.opened_at

        # Compare ground truth metadata
        for tra, trb in zip(world_a.truths, world_b.truths):
            assert tra.model_dump() == trb.model_dump()

    def test_different_seed_different_world(self):
        """Verifies that different seeds yield distinct randomized transactions."""
        world_a = generate_synthetic_world(seed=42)
        world_b = generate_synthetic_world(seed=999)

        # Transaction amounts or timing must diverge
        amounts_a = [t.amount_minor_units for t in world_a.transactions]
        amounts_b = [t.amount_minor_units for t in world_b.transactions]
        assert amounts_a != amounts_b


# ── 2. Valid Canonical Events ─────────────────────────────────────────────────


@pytest.fixture(scope="module")
def world() -> SyntheticWorld:
    return generate_synthetic_world(seed=42)


class TestCanonicalContractConformance:
    def test_all_transactions_valid_canonical(self, world: SyntheticWorld):
        """Every generated transaction strictly satisfies the canonical TransactionEvent schema."""
        assert len(world.transactions) > 0

        for txn in world.transactions:
            assert isinstance(txn, TransactionEvent)
            assert txn.schema_version == "1.0.0"
            assert txn.currency == "INR"
            assert txn.origin == EventOrigin.SYNTHETIC
            assert txn.amount_minor_units >= 0
            assert txn.occurred_at.tzinfo is not None
            assert txn.observed_at.tzinfo is not None
            assert txn.observed_at >= txn.occurred_at
            assert isinstance(txn.sender, AccountReference)
            assert isinstance(txn.receiver, AccountReference)
            assert txn.sender.account_id != ""
            assert txn.receiver.account_id != ""

            # Round-trip JSON serialization
            serialized = txn.model_dump_json()
            restored = TransactionEvent.model_validate_json(serialized)
            assert restored == txn

    def test_no_ground_truth_inside_transactions(self, world: SyntheticWorld):
        """Ground-truth labels (is_fraud, taint, score) must NOT be present in TransactionEvent."""
        for txn in world.transactions:
            dumped = txn.model_dump()
            assert "is_fraud" not in dumped
            assert "taint" not in dumped
            assert "risk_score" not in dumped
            assert "ground_truth" not in dumped

    def test_all_cases_valid_canonical(self, world: SyntheticWorld):
        """Every generated case strictly satisfies the canonical FraudCase schema."""
        assert len(world.cases) > 0

        for case in world.cases:
            assert isinstance(case, FraudCase)
            assert case.schema_version == "1.0.0"
            assert case.opened_at.tzinfo is not None
            assert case.updated_at.tzinfo is not None
            assert len(case.transaction_ids) > 0

            # Round-trip JSON serialization
            serialized = case.model_dump_json()
            restored = FraudCase.model_validate_json(serialized)
            assert restored == case


# ── 3. Scenario Topologies ────────────────────────────────────────────────────


class TestScenarioTopologies:
    def test_simple_chain_topology(self):
        result = generate_simple_chain_scenario(seed=42)
        truth = result.truth

        assert truth.scenario_type == "simple_chain"
        # Linear path has >= 4 hops (5 nodes)
        assert len(truth.intended_downstream_path) >= 5
        assert len(truth.fraud_transaction_ids) == len(truth.intended_downstream_path) - 1

        # Check path continuity: sender of hop i+1 is receiver of hop i
        fraud_txns = [t for t in result.transactions if t.transaction_id in truth.fraud_transaction_ids]
        fraud_txns.sort(key=lambda t: t.occurred_at)
        for i in range(len(fraud_txns) - 1):
            assert fraud_txns[i].receiver.account_id == fraud_txns[i + 1].sender.account_id

    def test_fan_out_topology(self):
        result = generate_fan_out_scenario(seed=42)
        truth = result.truth

        assert truth.scenario_type == "fan_out"
        assert truth.source_account is not None

        # Verify 1 source fans out to >= 3 distinct mules
        splits = [t for t in result.transactions if t.sender.account_id == truth.source_account]
        assert len(splits) >= 4
        recipient_ids = {t.receiver.account_id for t in splits}
        assert len(recipient_ids) == len(splits)

    def test_fan_in_topology(self):
        result = generate_fan_in_scenario(seed=42)
        truth = result.truth

        assert truth.scenario_type == "fan_in"
        assert truth.expected_convergence_account is not None

        # Multiple feeder accounts send to aggregator
        inflows = [
            t for t in result.transactions
            if t.receiver.account_id == truth.expected_convergence_account
        ]
        assert len(inflows) >= 3
        feeder_ids = {t.sender.account_id for t in inflows}
        assert len(feeder_ids) >= 3

    def test_fan_out_fan_in_chokepoint_topology(self):
        result = generate_fan_out_fan_in_scenario(seed=42)
        truth = result.truth

        assert truth.scenario_type == "fan_out_fan_in"
        chokepoint_id = truth.expected_convergence_account
        assert chokepoint_id is not None

        # Intermediate accounts all converge on chokepoint
        convergences = [t for t in result.transactions if t.receiver.account_id == chokepoint_id]
        assert len(convergences) >= 3

        # And chokepoint subsequently sends forward to exit
        outflows = [t for t in result.transactions if t.sender.account_id == chokepoint_id]
        assert len(outflows) == 1
        assert outflows[0].amount_minor_units > 0


# ── 4. Known Fraud Labels & Ground-Truth ──────────────────────────────────────


class TestKnownFraudLabels:
    def test_truth_references_exist_in_world(self):
        world = generate_synthetic_world(seed=42)
        world_txn_ids = {t.transaction_id for t in world.transactions}
        world_acct_ids = {a.account_id for a in world.accounts}

        for truth in world.truths:
            assert isinstance(truth, ScenarioTruth)

            # All seed transactions exist
            for stxn in truth.seed_transaction_ids:
                assert stxn in world_txn_ids

            # All fraud-linked transactions exist
            for ftxn in truth.fraud_transaction_ids:
                assert ftxn in world_txn_ids

            # All fraud accounts exist in account directory
            for facct in truth.fraud_accounts:
                assert facct in world_acct_ids


# ── 5. Cold-Start Accounts ────────────────────────────────────────────────────


class TestColdStartScenario:
    def test_cold_start_accounts_have_no_prior_history(self):
        """Verifies that cold-start accounts have ZERO historical events before the fraud seed."""
        result = generate_cold_start_scenario(seed=42)
        truth = result.truth

        cold_account_ids = set(truth.metadata["cold_start_accounts"])
        assert len(cold_account_ids) >= 2

        # Identify the seed transaction timestamp
        seed_txn_id = truth.seed_transaction_ids[0]
        seed_txn = next(t for t in result.transactions if t.transaction_id == seed_txn_id)
        seed_time = seed_txn.occurred_at

        # Verify that for any transaction involving cold accounts, occurred_at >= seed_time
        cold_txns = [
            t for t in result.transactions
            if t.sender.account_id in cold_account_ids or t.receiver.account_id in cold_account_ids
        ]
        assert len(cold_txns) > 0

        for t in cold_txns:
            assert t.occurred_at >= seed_time, (
                f"Cold-start account {t.sender.account_id}/{t.receiver.account_id} "
                f"participated in transaction {t.transaction_id} at {t.occurred_at} "
                f"BEFORE the fraud seed at {seed_time}!"
            )

        # Contrast: Established accounts (victim) DO have transactions before seed_time
        prior_victim_txns = [
            t for t in result.transactions
            if (t.sender.account_id == truth.source_account or t.receiver.account_id == truth.source_account)
            and t.occurred_at < seed_time
        ]
        assert len(prior_victim_txns) >= 5, "Established accounts must have historical profile"


# ── 6. Cross-Bank Events ──────────────────────────────────────────────────────


class TestCrossBankScenario:
    def test_cross_bank_traverses_multiple_institutions(self):
        """Verifies that the cross-bank scenario spans at least 3-4 distinct synthetic banks."""
        result = generate_cross_bank_scenario(seed=42)
        truth = result.truth

        fraud_txns = [t for t in result.transactions if t.transaction_id in truth.fraud_transaction_ids]
        institutions = set()
        for t in fraud_txns:
            assert t.sender.institution in SYNTHETIC_BANKS
            assert t.receiver.institution in SYNTHETIC_BANKS
            institutions.add(t.sender.institution)
            institutions.add(t.receiver.institution)

        # Spans BANK_A, BANK_B, BANK_C, BANK_D
        assert institutions == {"BANK_A", "BANK_B", "BANK_C", "BANK_D"}

        # Verifies cross-bank settlement channels are utilized
        channels = {t.channel for t in fraud_txns}
        assert len(channels.intersection({TransactionChannel.IMPS, TransactionChannel.NEFT, TransactionChannel.RTGS})) >= 2


# ── 7. Smurfing Scenario ──────────────────────────────────────────────────────


class TestSmurfingScenario:
    def test_smurfing_many_small_transactions(self):
        """Verifies that smurfing produces deliberately small micro-transactions below benchmark threshold."""
        result = generate_smurfing_scenario(seed=42)
        truth = result.truth

        assert len(truth.fraud_transaction_ids) >= 15  # Structuring requirement: high transaction count
        synthetic_threshold_paise = 5_000_000  # configurable synthetic micro-flow threshold (₹50,000)

        smurf_txns = [t for t in result.transactions if t.transaction_id in truth.fraud_transaction_ids]
        assert len(smurf_txns) == len(truth.fraud_transaction_ids)

        for t in smurf_txns:
            assert t.amount_minor_units < synthetic_threshold_paise, (
                f"Smurfed transaction {t.transaction_id} amount {t.amount_minor_units} "
                f"exceeds configurable synthetic micro-flow threshold {synthetic_threshold_paise}!"
            )

        # Sum of smurfed chunks matches injected fraud total
        assert sum(t.amount_minor_units for t in smurf_txns) == truth.injected_fraud_amount


# ── 8. Commingling Scenario ───────────────────────────────────────────────────


class TestComminglingScenario:
    def test_commingling_receives_both_legitimate_and_fraud_inflow(self):
        """Verifies that the commingling account receives both dirty and clean money."""
        result = generate_commingling_scenario(seed=42)
        truth = result.truth

        commingler_id = truth.expected_convergence_account
        assert commingler_id is not None

        # All inflows to the commingler
        inflows = [t for t in result.transactions if t.receiver.account_id == commingler_id]
        assert len(inflows) >= 4

        # Fraud inflow from fraud source
        fraud_inflows = [t for t in inflows if t.sender.account_id == truth.source_account]
        assert len(fraud_inflows) == 1
        assert fraud_inflows[0].transaction_id in truth.fraud_transaction_ids

        # Legitimate inflows from other clean customer accounts
        legit_inflows = [t for t in inflows if t.sender.account_id != truth.source_account]
        assert len(legit_inflows) >= 3
        for lt in legit_inflows:
            assert lt.transaction_id not in truth.fraud_transaction_ids


# ── 9. Rapid Pass-Through ─────────────────────────────────────────────────────


class TestRapidPassThroughScenario:
    def test_rapid_pass_through_dwell_time(self):
        """Verifies that inter-hop delays are sub-minute."""
        result = generate_rapid_pass_through_scenario(seed=42)
        truth = result.truth

        fraud_txns = [t for t in result.transactions if t.transaction_id in truth.fraud_transaction_ids]
        fraud_txns.sort(key=lambda t: t.occurred_at)

        for i in range(len(fraud_txns) - 1):
            delta_seconds = (fraud_txns[i + 1].occurred_at - fraud_txns[i].occurred_at).total_seconds()
            assert delta_seconds < 60.0, f"Dwell time {delta_seconds}s exceeds rapid threshold 60s"


# ── 10. Benign High-Volume Merchant (Negative Control) ───────────────────────


class TestBenignMerchantScenario:
    def test_negative_control_has_zero_fraud(self):
        """Verifies that the benign merchant generates substantial traffic with 0 fraud."""
        result = generate_benign_high_volume_merchant_scenario(seed=42)
        truth = result.truth

        assert truth.scenario_type == "benign_high_volume_merchant"
        assert truth.case_id is None
        assert truth.injected_fraud_amount == 0
        assert len(truth.fraud_transaction_ids) == 0
        assert len(truth.seed_transaction_ids) == 0
        assert len(truth.fraud_accounts) == 0

        # Substantial legitimate retail transaction volume
        assert len(result.transactions) >= 25
        assert len(result.cases) == 0


# ── 11. Volume Metrics & Injected Capital vs. Edge Volume Distinction ─────────


class TestVolumeMetrics:
    def test_injected_capital_vs_edge_volume_semantics(self, world: SyntheticWorld):
        """Verifies that Injected Fraud Capital and Fraud-Linked Edge Volume are separated and semantically valid.

        Fraud-Linked Edge Volume can exceed Injected Fraud Capital when the same capital
        traverses multiple transaction edges. It must not be interpreted as unique stolen capital.
        """
        summary = compute_world_summary(world, seed=42)

        injected_capital = summary["injected_fraud_capital_paise"]
        edge_volume = summary["fraud_linked_edge_volume_paise"]
        legit_volume = summary["legitimate_transaction_volume_paise"]
        total_volume = summary["total_transaction_volume_paise"]

        assert injected_capital > 0
        assert edge_volume > 0
        assert legit_volume > 0

        # Total transaction volume must strictly equal fraud-linked edge volume + legitimate volume
        assert total_volume == edge_volume + legit_volume

        # In this multi-hop benchmark world, edge volume exceeds injected capital because capital hops across multiple edges
        assert edge_volume >= injected_capital

