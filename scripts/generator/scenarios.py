"""
AEGIS-Flow Synthetic Generator — Scenario Families
===================================================

Implements the 10 canonical synthetic scenario families:
1. simple_chain — Linear multi-hop laundering path with decoy noise
2. fan_out — 1-to-many illicit fund dispersion across mules
3. fan_in — Many-to-1 illicit fund consolidation into an aggregator
4. fan_out_fan_in — Diamond topology with a definitive chokepoint account
5. commingling — Mule account receiving both illicit and legitimate inflows
6. cold_start — Fraud seed entering newly created accounts with zero history
7. cross_bank — Inter-bank laundering chain spanning BANK_A, BANK_B, BANK_C, BANK_D
8. smurfing — Structuring: deliberately small micro-transactions below a configurable synthetic micro-flow threshold
9. rapid_pass_through — High-velocity hops with sub-minute dwell times
10. benign_high_volume_merchant — Negative control: legitimate high-degree merchant hub
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from contracts.account import AccountReference
from contracts.case import FraudCase
from contracts.enums import CaseOrigin, CaseStatus, TransactionChannel, TransactionStatus
from contracts.transaction import TransactionEvent
from scripts.generator.accounts import AccountPool, AccountRole, SYNTHETIC_BANKS, create_account
from scripts.generator.fraud import (
    build_fan_in_consolidation,
    build_fan_out_split,
    build_linear_hop_chain,
    build_smurfing_transfers,
    create_fraud_case,
)
from scripts.generator.legitimate import (
    generate_decoy_transactions,
    generate_historical_profile,
    make_transaction,
)
from scripts.generator.truth import ScenarioTruth

UTC = timezone.utc


@dataclass(frozen=True)
class ScenarioResult:
    """Complete output package for a single generated scenario."""

    scenario_id: str
    scenario_type: str
    transactions: list[TransactionEvent]
    cases: list[FraudCase]
    truth: ScenarioTruth
    accounts: list[AccountReference]


# ── 1. Simple Chain ───────────────────────────────────────────────────────────


def generate_simple_chain_scenario(
    scenario_id: str = "sc-01-simple-chain",
    seed: int = 42,
    base_time: datetime | None = None,
) -> ScenarioResult:
    """Family 1: Linear 4-hop chain: Victim -> Mule 1 -> Mule 2 -> Mule 3 -> Cashout."""
    rng = random.Random(seed)
    start = base_time or datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC)
    pool = AccountPool(prefix=f"{scenario_id}-acc")

    victim = pool.new_account(AccountRole.VICTIM, "BANK_A", "Victim Corporation")
    mule1 = pool.new_account(AccountRole.MULE, "BANK_A", "Tier-1 Mule")
    mule2 = pool.new_account(AccountRole.MULE, "BANK_B", "Tier-2 Mule")
    mule3 = pool.new_account(AccountRole.MULE, "BANK_B", "Tier-3 Mule")
    cashout = pool.new_account(AccountRole.EXFILTRATION, "BANK_C", "Cashout Account")

    path = [victim, mule1, mule2, mule3, cashout]
    fraud_amount = 50_000_000  # ₹5,00,000

    fraud_txns = build_linear_hop_chain(
        path=path,
        initial_amount=fraud_amount,
        start_time=start,
        hop_delay_seconds=300.0,  # 5 minutes per hop
        id_prefix=scenario_id,
        fee_percentage=0.015,
        channel=TransactionChannel.UPI,
    )

    # Decoy activity around intermediary mules
    decoy_counterparties = [
        pool.new_account(AccountRole.LEGITIMATE, "BANK_A", "Local Supermarket"),
        pool.new_account(AccountRole.LEGITIMATE, "BANK_B", "Utility Board"),
        pool.new_account(AccountRole.LEGITIMATE, "BANK_C", "Peer Contact"),
    ]
    decoy_txns = generate_decoy_transactions(
        accounts=[mule1, mule2, mule3],
        external_counterparties=decoy_counterparties,
        start_time=start - timedelta(hours=2),
        end_time=start + timedelta(hours=3),
        count=6,
        rng=rng,
        id_prefix=f"{scenario_id}-decoy",
    )

    all_txns = sorted(fraud_txns + decoy_txns, key=lambda t: t.occurred_at)
    seed_txn = fraud_txns[0]

    case = create_fraud_case(
        case_id=f"case-{scenario_id}",
        title="Unauthorized Business Compromise — Linear Chain",
        description="Linear laundering chain through 3 mule intermediaries to external bank cashout.",
        transaction_ids=[seed_txn.transaction_id],
        opened_at=seed_txn.occurred_at + timedelta(minutes=15),
        origin=CaseOrigin.CUSTOMER_REPORT,
    )

    truth = ScenarioTruth(
        scenario_id=scenario_id,
        scenario_type="simple_chain",
        case_id=case.case_id,
        seed_transaction_ids=[seed_txn.transaction_id],
        fraud_transaction_ids=[t.transaction_id for t in fraud_txns],
        fraud_accounts=[a.account_id for a in path[1:]],
        source_account=victim.account_id,
        intended_downstream_path=[a.account_id for a in path],
        intended_next_hop_label={
            path[i].account_id: path[i + 1].account_id for i in range(len(path) - 1)
        },
        expected_convergence_account=None,
        injected_fraud_amount=fraud_amount,
        metadata={"hop_count": len(fraud_txns), "hop_delay_seconds": 300.0},
    )

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type="simple_chain",
        transactions=all_txns,
        cases=[case],
        truth=truth,
        accounts=pool.all_accounts(),
    )


# ── 2. Fan-Out ────────────────────────────────────────────────────────────────


def generate_fan_out_scenario(
    scenario_id: str = "sc-02-fan-out",
    seed: int = 43,
    base_time: datetime | None = None,
) -> ScenarioResult:
    """Family 2: 1-to-many dispersion: Source splits illicit capital across multiple mules."""
    rng = random.Random(seed)
    start = base_time or datetime(2026, 10, 8, 10, 0, 0, tzinfo=UTC)
    pool = AccountPool(prefix=f"{scenario_id}-acc")

    source = pool.new_account(AccountRole.VICTIM, "BANK_A", "Payroll Escrow Account")
    mules = [
        pool.new_account(AccountRole.MULE, "BANK_A", "Dispersion Mule 1"),
        pool.new_account(AccountRole.MULE, "BANK_B", "Dispersion Mule 2"),
        pool.new_account(AccountRole.MULE, "BANK_C", "Dispersion Mule 3"),
        pool.new_account(AccountRole.MULE, "BANK_D", "Dispersion Mule 4"),
    ]

    total_amount = 80_000_000  # ₹8,00,000

    fraud_txns = build_fan_out_split(
        source=source,
        mules=mules,
        total_amount=total_amount,
        start_time=start,
        id_prefix=scenario_id,
        channel=TransactionChannel.IMPS,
        time_jitter_seconds=60.0,
        rng=rng,
    )

    decoy_counterparties = [
        pool.new_account(AccountRole.LEGITIMATE, "BANK_A", "Telecom Provider"),
        pool.new_account(AccountRole.LEGITIMATE, "BANK_B", "Ride Share"),
    ]
    decoy_txns = generate_decoy_transactions(
        accounts=mules,
        external_counterparties=decoy_counterparties,
        start_time=start - timedelta(hours=1),
        end_time=start + timedelta(hours=2),
        count=5,
        rng=rng,
        id_prefix=f"{scenario_id}-decoy",
    )

    all_txns = sorted(fraud_txns + decoy_txns, key=lambda t: t.occurred_at)

    case = create_fraud_case(
        case_id=f"case-{scenario_id}",
        title="Escrow Account Drain — Fan-Out Layering",
        description="Parallel distribution of stolen payroll funds across 4 mule accounts.",
        transaction_ids=[t.transaction_id for t in fraud_txns],
        opened_at=start + timedelta(minutes=10),
        origin=CaseOrigin.BANK_DETECTION,
    )

    truth = ScenarioTruth(
        scenario_id=scenario_id,
        scenario_type="fan_out",
        case_id=case.case_id,
        seed_transaction_ids=[t.transaction_id for t in fraud_txns],
        fraud_transaction_ids=[t.transaction_id for t in fraud_txns],
        fraud_accounts=[m.account_id for m in mules],
        source_account=source.account_id,
        intended_downstream_path=[source.account_id] + [m.account_id for m in mules],
        intended_next_hop_label={
            source.account_id: [m.account_id for m in mules]
        },
        expected_convergence_account=None,
        injected_fraud_amount=total_amount,
        metadata={"fan_out_degree": len(mules)},
    )

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type="fan_out",
        transactions=all_txns,
        cases=[case],
        truth=truth,
        accounts=pool.all_accounts(),
    )


# ── 3. Fan-In ─────────────────────────────────────────────────────────────────


def generate_fan_in_scenario(
    scenario_id: str = "sc-03-fan-in",
    seed: int = 44,
    base_time: datetime | None = None,
) -> ScenarioResult:
    """Family 3: Many-to-1 aggregation: Multiple feeder accounts consolidate to one collector."""
    rng = random.Random(seed)
    start = base_time or datetime(2026, 10, 8, 11, 0, 0, tzinfo=UTC)
    pool = AccountPool(prefix=f"{scenario_id}-acc")

    feeders = [
        pool.new_account(AccountRole.MULE, "BANK_A", "Feeder Mule A"),
        pool.new_account(AccountRole.MULE, "BANK_B", "Feeder Mule B"),
        pool.new_account(AccountRole.MULE, "BANK_C", "Feeder Mule C"),
    ]
    aggregator = pool.new_account(AccountRole.AGGREGATOR, "BANK_D", "Central Collector Account")

    inflows = [25_000_000, 20_000_000, 30_000_000]  # Total: ₹7,50,000 (75,000,000 paise)
    total_amount = sum(inflows)

    fraud_txns = build_fan_in_consolidation(
        feeders=feeders,
        aggregator=aggregator,
        amounts=inflows,
        start_time=start,
        id_prefix=scenario_id,
        channel=TransactionChannel.RTGS,
        time_window_seconds=900.0,
        rng=rng,
    )

    decoy_parties = [
        pool.new_account(AccountRole.LEGITIMATE, "BANK_A", "Clean Supplier"),
    ]
    decoy_txns = generate_decoy_transactions(
        accounts=feeders,
        external_counterparties=decoy_parties,
        start_time=start - timedelta(hours=1),
        end_time=start + timedelta(hours=2),
        count=4,
        rng=rng,
        id_prefix=f"{scenario_id}-decoy",
    )

    all_txns = sorted(fraud_txns + decoy_txns, key=lambda t: t.occurred_at)

    case = create_fraud_case(
        case_id=f"case-{scenario_id}",
        title="Multi-Source Funneling — Fan-In Consolidation",
        description="High-value consolidation of dispersed funds into a single cross-bank aggregator.",
        transaction_ids=[t.transaction_id for t in fraud_txns],
        opened_at=start + timedelta(minutes=20),
        origin=CaseOrigin.SHARED_INTELLIGENCE,
    )

    truth = ScenarioTruth(
        scenario_id=scenario_id,
        scenario_type="fan_in",
        case_id=case.case_id,
        seed_transaction_ids=[t.transaction_id for t in fraud_txns],
        fraud_transaction_ids=[t.transaction_id for t in fraud_txns],
        fraud_accounts=[f.account_id for f in feeders] + [aggregator.account_id],
        source_account=None,  # Multi-source
        intended_downstream_path=[f.account_id for f in feeders] + [aggregator.account_id],
        intended_next_hop_label={
            f.account_id: aggregator.account_id for f in feeders
        },
        expected_convergence_account=aggregator.account_id,
        injected_fraud_amount=total_amount,
        metadata={"feeder_count": len(feeders), "convergence_account": aggregator.account_id},
    )

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type="fan_in",
        transactions=all_txns,
        cases=[case],
        truth=truth,
        accounts=pool.all_accounts(),
    )


# ── 4. Fan-Out Fan-In (Diamond / Chokepoint) ───────────────────────────────────


def generate_fan_out_fan_in_scenario(
    scenario_id: str = "sc-04-fan-out-fan-in",
    seed: int = 45,
    base_time: datetime | None = None,
) -> ScenarioResult:
    """Family 4: Diamond topology: Source -> Layer 1 -> Splits -> Reconverges at Chokepoint -> Exit."""
    rng = random.Random(seed)
    start = base_time or datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    pool = AccountPool(prefix=f"{scenario_id}-acc")

    victim = pool.new_account(AccountRole.VICTIM, "BANK_A", "Victim Account")
    layer1 = pool.new_account(AccountRole.MULE, "BANK_A", "Layer-1 Splitter")
    layer2_mules = [
        pool.new_account(AccountRole.MULE, "BANK_B", "Layer-2 Intermediate A"),
        pool.new_account(AccountRole.MULE, "BANK_B", "Layer-2 Intermediate B"),
        pool.new_account(AccountRole.MULE, "BANK_C", "Layer-2 Intermediate C"),
    ]
    chokepoint = pool.new_account(AccountRole.CHOKEPOINT, "BANK_C", "Target Chokepoint Hub")
    exit_account = pool.new_account(AccountRole.EXFILTRATION, "BANK_D", "Final Exfiltration Wallet")

    fraud_amount = 60_000_000  # ₹6,00,000
    fraud_txns: list[TransactionEvent] = []

    # Step 1: Victim -> Layer 1
    t1 = start
    fraud_txns.append(
        make_transaction(
            event_id=f"evt-{scenario_id}-01-seed",
            transaction_id=f"txn-{scenario_id}-01-seed",
            sender=victim,
            receiver=layer1,
            amount_minor_units=fraud_amount,
            occurred_at=t1,
            channel=TransactionChannel.UPI,
        )
    )

    # Step 2: Layer 1 splits to 3 intermediaries (Fan-Out)
    t2 = t1 + timedelta(minutes=5)
    split_amt = fraud_amount // 3
    for idx, m in enumerate(layer2_mules):
        fraud_txns.append(
            make_transaction(
                event_id=f"evt-{scenario_id}-02-split{idx+1:02d}",
                transaction_id=f"txn-{scenario_id}-02-split{idx+1:02d}",
                sender=layer1,
                receiver=m,
                amount_minor_units=split_amt,
                occurred_at=t2 + timedelta(seconds=idx * 20),
                channel=TransactionChannel.IMPS,
            )
        )

    # Step 3: All 3 intermediaries transfer to Chokepoint (Fan-In)
    t3 = t2 + timedelta(minutes=10)
    for idx, m in enumerate(layer2_mules):
        fraud_txns.append(
            make_transaction(
                event_id=f"evt-{scenario_id}-03-reconv{idx+1:02d}",
                transaction_id=f"txn-{scenario_id}-03-reconv{idx+1:02d}",
                sender=m,
                receiver=chokepoint,
                amount_minor_units=split_amt - 10_000,  # small fee
                occurred_at=t3 + timedelta(seconds=idx * 25),
                channel=TransactionChannel.IMPS,
            )
        )

    # Step 4: Chokepoint -> Exit
    t4 = t3 + timedelta(minutes=15)
    recombined_total = (split_amt - 10_000) * 3
    fraud_txns.append(
        make_transaction(
            event_id=f"evt-{scenario_id}-04-exit",
            transaction_id=f"txn-{scenario_id}-04-exit",
            sender=chokepoint,
            receiver=exit_account,
            amount_minor_units=recombined_total,
            occurred_at=t4,
            channel=TransactionChannel.NEFT,
        )
    )

    # Decoy background noise
    decoy_parties = [
        pool.new_account(AccountRole.LEGITIMATE, "BANK_B", "Decoy Merchant"),
    ]
    decoy_txns = generate_decoy_transactions(
        accounts=layer2_mules,
        external_counterparties=decoy_parties,
        start_time=start,
        end_time=t4 + timedelta(minutes=30),
        count=5,
        rng=rng,
        id_prefix=f"{scenario_id}-decoy",
    )

    all_txns = sorted(fraud_txns + decoy_txns, key=lambda t: t.occurred_at)

    case = create_fraud_case(
        case_id=f"case-{scenario_id}",
        title="Diamond Topology Flow — Chokepoint Convergence",
        description="Split-and-recombine laundering flow converging onto chokepoint before exfiltration.",
        transaction_ids=[fraud_txns[0].transaction_id],
        opened_at=t1 + timedelta(minutes=8),
        origin=CaseOrigin.CUSTOMER_REPORT,
    )

    truth = ScenarioTruth(
        scenario_id=scenario_id,
        scenario_type="fan_out_fan_in",
        case_id=case.case_id,
        seed_transaction_ids=[fraud_txns[0].transaction_id],
        fraud_transaction_ids=[t.transaction_id for t in fraud_txns],
        fraud_accounts=[layer1.account_id]
        + [m.account_id for m in layer2_mules]
        + [chokepoint.account_id, exit_account.account_id],
        source_account=victim.account_id,
        intended_downstream_path=[victim.account_id, layer1.account_id, chokepoint.account_id, exit_account.account_id],
        intended_next_hop_label={
            victim.account_id: layer1.account_id,
            layer1.account_id: [m.account_id for m in layer2_mules],
            layer2_mules[0].account_id: chokepoint.account_id,
            layer2_mules[1].account_id: chokepoint.account_id,
            layer2_mules[2].account_id: chokepoint.account_id,
            chokepoint.account_id: exit_account.account_id,
        },
        expected_convergence_account=chokepoint.account_id,
        injected_fraud_amount=fraud_amount,
        metadata={
            "chokepoint_account": chokepoint.account_id,
            "intermediate_count": len(layer2_mules),
        },
    )

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type="fan_out_fan_in",
        transactions=all_txns,
        cases=[case],
        truth=truth,
        accounts=pool.all_accounts(),
    )


# ── 5. Commingling ────────────────────────────────────────────────────────────


def generate_commingling_scenario(
    scenario_id: str = "sc-05-commingling",
    seed: int = 46,
    base_time: datetime | None = None,
) -> ScenarioResult:
    """Family 5: Commingling: Account receives both illicit and legitimate inflows before forwarding."""
    rng = random.Random(seed)
    start = base_time or datetime(2026, 10, 8, 13, 0, 0, tzinfo=UTC)
    pool = AccountPool(prefix=f"{scenario_id}-acc")

    fraud_source = pool.new_account(AccountRole.VICTIM, "BANK_A", "Compromised Corporate Source")
    commingler = pool.new_account(AccountRole.COMMINGLER, "BANK_B", "Commingling Merchant/Mule")
    exit_account = pool.new_account(AccountRole.EXFILTRATION, "BANK_C", "Downstream Exfiltration Account")

    # 5 clean customers providing legitimate revenue to the commingler
    clean_customers = [
        pool.new_account(AccountRole.LEGITIMATE, "BANK_A", f"Legitimate Customer {i+1}")
        for i in range(5)
    ]

    fraud_amount = 30_000_000  # ₹3,00,000 illicit inflow
    fraud_txns: list[TransactionEvent] = []
    legitimate_txns: list[TransactionEvent] = []

    # 1. Illicit inflow
    t_fraud = start
    fraud_inflow = make_transaction(
        event_id=f"evt-{scenario_id}-fraud-in",
        transaction_id=f"txn-{scenario_id}-fraud-in",
        sender=fraud_source,
        receiver=commingler,
        amount_minor_units=fraud_amount,
        occurred_at=t_fraud,
        channel=TransactionChannel.RTGS,
    )
    fraud_txns.append(fraud_inflow)

    # 2. Legitimate clean inflows over surrounding hours
    clean_total = 0
    for idx, cust in enumerate(clean_customers):
        amt = rng.randint(2_500_000, 6_000_000)  # ₹25,000 to ₹60,000 each
        clean_total += amt
        t_clean = start + timedelta(minutes=rng.uniform(-30, 45))
        legitimate_txns.append(
            make_transaction(
                event_id=f"evt-{scenario_id}-clean-{idx+1:02d}",
                transaction_id=f"txn-{scenario_id}-clean-{idx+1:02d}",
                sender=cust,
                receiver=commingler,
                amount_minor_units=amt,
                occurred_at=t_clean,
                channel=TransactionChannel.UPI,
            )
        )

    # 3. Blended outflow (commingled money forwarded downstream)
    t_outflow = start + timedelta(hours=1)
    blended_outflow_amount = fraud_amount + (clean_total // 2)
    fraud_outflow = make_transaction(
        event_id=f"evt-{scenario_id}-blended-out",
        transaction_id=f"txn-{scenario_id}-blended-out",
        sender=commingler,
        receiver=exit_account,
        amount_minor_units=blended_outflow_amount,
        occurred_at=t_outflow,
        channel=TransactionChannel.NEFT,
    )
    fraud_txns.append(fraud_outflow)

    all_txns = sorted(fraud_txns + legitimate_txns, key=lambda t: t.occurred_at)

    case = create_fraud_case(
        case_id=f"case-{scenario_id}",
        title="Commercial Mixing — Commingling Inflow Analysis",
        description="Illicit capital blended with genuine commercial retail turnover.",
        transaction_ids=[fraud_inflow.transaction_id],
        opened_at=t_fraud + timedelta(minutes=25),
        origin=CaseOrigin.BANK_DETECTION,
    )

    truth = ScenarioTruth(
        scenario_id=scenario_id,
        scenario_type="commingling",
        case_id=case.case_id,
        seed_transaction_ids=[fraud_inflow.transaction_id],
        fraud_transaction_ids=[t.transaction_id for t in fraud_txns],
        fraud_accounts=[commingler.account_id, exit_account.account_id],
        source_account=fraud_source.account_id,
        intended_downstream_path=[fraud_source.account_id, commingler.account_id, exit_account.account_id],
        intended_next_hop_label={
            fraud_source.account_id: commingler.account_id,
            commingler.account_id: exit_account.account_id,
        },
        expected_convergence_account=commingler.account_id,
        injected_fraud_amount=fraud_amount,
        metadata={
            "commingler_account": commingler.account_id,
            "legitimate_inflow_minor_units": clean_total,
            "legitimate_inflow_count": len(clean_customers),
        },
    )

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type="commingling",
        transactions=all_txns,
        cases=[case],
        truth=truth,
        accounts=pool.all_accounts(),
    )


# ── 6. Cold Start ─────────────────────────────────────────────────────────────


def generate_cold_start_scenario(
    scenario_id: str = "sc-06-cold-start",
    seed: int = 47,
    base_time: datetime | None = None,
) -> ScenarioResult:
    """Family 6: Cold start: Fraud seed enters newly created account(s) with zero prior history."""
    rng = random.Random(seed)
    seed_time = base_time or datetime(2026, 10, 8, 14, 0, 0, tzinfo=UTC)
    pool = AccountPool(prefix=f"{scenario_id}-acc")

    victim = pool.new_account(AccountRole.VICTIM, "BANK_A", "Established Victim Entity")
    cold_mule1 = pool.new_account(AccountRole.COLD_START, "BANK_B", "Cold-Start Mule 1 (Brand New)")
    cold_mule2 = pool.new_account(AccountRole.COLD_START, "BANK_C", "Cold-Start Mule 2 (Brand New)")
    exit_account = pool.new_account(AccountRole.EXFILTRATION, "BANK_D", "Cashout Endpoint")

    # Regular benchmark accounts for generating history
    established_background = [
        pool.new_account(AccountRole.LEGITIMATE, "BANK_A", "Established Business 1"),
        pool.new_account(AccountRole.LEGITIMATE, "BANK_A", "Established Business 2"),
    ]

    # Pre-seed history: generated ONLY for established accounts (victim & background)
    # CRITICAL INVARIANT: cold_mule1 and cold_mule2 must have NO transactions prior to seed_time!
    historical_txns = generate_historical_profile(
        established_accounts=[victim],
        benchmark_parties=established_background,
        cutoff_time=seed_time,
        history_days=7,
        txns_per_account=6,
        rng=rng,
        id_prefix=f"{scenario_id}-hist",
    )

    # Fraud flow initiated at seed_time
    fraud_amount = 45_000_000  # ₹4,50,000
    fraud_path = [victim, cold_mule1, cold_mule2, exit_account]

    fraud_txns = build_linear_hop_chain(
        path=fraud_path,
        initial_amount=fraud_amount,
        start_time=seed_time,
        hop_delay_seconds=120.0,
        id_prefix=f"{scenario_id}-fraud",
        fee_percentage=0.01,
        channel=TransactionChannel.UPI,
    )

    all_txns = sorted(historical_txns + fraud_txns, key=lambda t: t.occurred_at)
    seed_txn = fraud_txns[0]

    case = create_fraud_case(
        case_id=f"case-{scenario_id}",
        title="Zero-History Ingress — Cold-Start Layering",
        description="Fraudulent transfer directed into recently provisioned accounts with no prior telemetry.",
        transaction_ids=[seed_txn.transaction_id],
        opened_at=seed_time + timedelta(minutes=10),
        origin=CaseOrigin.BANK_DETECTION,
    )

    truth = ScenarioTruth(
        scenario_id=scenario_id,
        scenario_type="cold_start",
        case_id=case.case_id,
        seed_transaction_ids=[seed_txn.transaction_id],
        fraud_transaction_ids=[t.transaction_id for t in fraud_txns],
        fraud_accounts=[cold_mule1.account_id, cold_mule2.account_id, exit_account.account_id],
        source_account=victim.account_id,
        intended_downstream_path=[a.account_id for a in fraud_path],
        intended_next_hop_label={
            victim.account_id: cold_mule1.account_id,
            cold_mule1.account_id: cold_mule2.account_id,
            cold_mule2.account_id: exit_account.account_id,
        },
        expected_convergence_account=None,
        injected_fraud_amount=fraud_amount,
        metadata={
            "cold_start_accounts": [cold_mule1.account_id, cold_mule2.account_id],
            "seed_time_iso": seed_time.isoformat(),
        },
    )

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type="cold_start",
        transactions=all_txns,
        cases=[case],
        truth=truth,
        accounts=pool.all_accounts(),
    )


# ── 7. Cross-Bank ─────────────────────────────────────────────────────────────


def generate_cross_bank_scenario(
    scenario_id: str = "sc-07-cross-bank",
    seed: int = 48,
    base_time: datetime | None = None,
) -> ScenarioResult:
    """Family 7: Cross-bank laundering: Explicitly traverses BANK_A -> BANK_B -> BANK_C -> BANK_D."""
    rng = random.Random(seed)
    start = base_time or datetime(2026, 10, 8, 15, 0, 0, tzinfo=UTC)
    pool = AccountPool(prefix=f"{scenario_id}-acc")

    acct_a = pool.new_account(AccountRole.VICTIM, "BANK_A", "Source Account @ BANK_A")
    acct_b = pool.new_account(AccountRole.MULE, "BANK_B", "Relay Mule @ BANK_B")
    acct_c = pool.new_account(AccountRole.MULE, "BANK_C", "Layering Mule @ BANK_C")
    acct_d = pool.new_account(AccountRole.EXFILTRATION, "BANK_D", "Settlement Account @ BANK_D")

    fraud_amount = 75_000_000  # ₹7,50,000
    fraud_txns: list[TransactionEvent] = []

    # Hop 1: BANK_A -> BANK_B via IMPS
    t1 = start
    fraud_txns.append(
        make_transaction(
            event_id=f"evt-{scenario_id}-hop01-a-b",
            transaction_id=f"txn-{scenario_id}-hop01-a-b",
            sender=acct_a,
            receiver=acct_b,
            amount_minor_units=fraud_amount,
            occurred_at=t1,
            channel=TransactionChannel.IMPS,
        )
    )

    # Hop 2: BANK_B -> BANK_C via NEFT
    t2 = t1 + timedelta(minutes=15)
    fraud_txns.append(
        make_transaction(
            event_id=f"evt-{scenario_id}-hop02-b-c",
            transaction_id=f"txn-{scenario_id}-hop02-b-c",
            sender=acct_b,
            receiver=acct_c,
            amount_minor_units=fraud_amount - 100_000,
            occurred_at=t2,
            channel=TransactionChannel.NEFT,
        )
    )

    # Hop 3: BANK_C -> BANK_D via RTGS
    t3 = t2 + timedelta(minutes=20)
    fraud_txns.append(
        make_transaction(
            event_id=f"evt-{scenario_id}-hop03-c-d",
            transaction_id=f"txn-{scenario_id}-hop03-c-d",
            sender=acct_c,
            receiver=acct_d,
            amount_minor_units=fraud_amount - 200_000,
            occurred_at=t3,
            channel=TransactionChannel.RTGS,
        )
    )

    # Decoy activity at intermediary banks
    decoy_parties = [
        pool.new_account(AccountRole.LEGITIMATE, "BANK_B", "Decoy B-Merchant"),
        pool.new_account(AccountRole.LEGITIMATE, "BANK_C", "Decoy C-Merchant"),
    ]
    decoy_txns = generate_decoy_transactions(
        accounts=[acct_b, acct_c],
        external_counterparties=decoy_parties,
        start_time=start - timedelta(hours=1),
        end_time=t3 + timedelta(hours=1),
        count=4,
        rng=rng,
        id_prefix=f"{scenario_id}-decoy",
    )

    all_txns = sorted(fraud_txns + decoy_txns, key=lambda t: t.occurred_at)

    case = create_fraud_case(
        case_id=f"case-{scenario_id}",
        title="Inter-Institutional Laundering — 4-Bank Hop",
        description="Cross-bank exfiltration spanning BANK_A, BANK_B, BANK_C, and BANK_D.",
        transaction_ids=[fraud_txns[0].transaction_id],
        opened_at=t1 + timedelta(minutes=12),
        origin=CaseOrigin.SHARED_INTELLIGENCE,
    )

    truth = ScenarioTruth(
        scenario_id=scenario_id,
        scenario_type="cross_bank",
        case_id=case.case_id,
        seed_transaction_ids=[fraud_txns[0].transaction_id],
        fraud_transaction_ids=[t.transaction_id for t in fraud_txns],
        fraud_accounts=[acct_b.account_id, acct_c.account_id, acct_d.account_id],
        source_account=acct_a.account_id,
        intended_downstream_path=[acct_a.account_id, acct_b.account_id, acct_c.account_id, acct_d.account_id],
        intended_next_hop_label={
            acct_a.account_id: acct_b.account_id,
            acct_b.account_id: acct_c.account_id,
            acct_c.account_id: acct_d.account_id,
        },
        expected_convergence_account=None,
        injected_fraud_amount=fraud_amount,
        metadata={
            "banks_involved": ["BANK_A", "BANK_B", "BANK_C", "BANK_D"],
            "rail_types": ["IMPS", "NEFT", "RTGS"],
        },
    )

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type="cross_bank",
        transactions=all_txns,
        cases=[case],
        truth=truth,
        accounts=pool.all_accounts(),
    )


# ── 8. Smurfing (Structuring) ─────────────────────────────────────────────────


def generate_smurfing_scenario(
    scenario_id: str = "sc-08-smurfing",
    seed: int = 49,
    base_time: datetime | None = None,
) -> ScenarioResult:
    """Family 8: Structuring / smurfing: Large total broken into deliberately small micro-transactions below a configurable synthetic micro-flow threshold."""
    rng = random.Random(seed)
    start = base_time or datetime(2026, 10, 8, 16, 0, 0, tzinfo=UTC)
    pool = AccountPool(prefix=f"{scenario_id}-acc")

    smurf_source = pool.new_account(AccountRole.VICTIM, "BANK_A", "Infiltrated Treasury Source")
    collectors = [
        pool.new_account(AccountRole.AGGREGATOR, "BANK_B", "Smurf Collector Alpha"),
        pool.new_account(AccountRole.AGGREGATOR, "BANK_C", "Smurf Collector Beta"),
    ]

    total_amount = 90_000_000  # ₹9,00,000 total
    chunk_count = 20           # 20 distinct small transactions
    synthetic_micro_flow_threshold = 5_000_000  # configurable synthetic micro-flow threshold (₹50,000 benchmark limit)

    fraud_txns = build_smurfing_transfers(
        sender=smurf_source,
        receivers=collectors,
        total_amount=total_amount,
        chunk_count=chunk_count,
        max_chunk_amount=synthetic_micro_flow_threshold,
        start_time=start,
        time_span_seconds=7200.0,  # over 2 hours
        id_prefix=scenario_id,
        rng=rng,
        channel=TransactionChannel.UPI,
    )

    case = create_fraud_case(
        case_id=f"case-{scenario_id}",
        title="Micro-Flow Structuring — High-Frequency Smurfing",
        description="20 deliberately small micro-transactions structured to remain sub-threshold according to the benchmark's configurable micro-flow threshold.",
        transaction_ids=[t.transaction_id for t in fraud_txns],
        opened_at=start + timedelta(hours=1),
        origin=CaseOrigin.BANK_DETECTION,
    )

    truth = ScenarioTruth(
        scenario_id=scenario_id,
        scenario_type="smurfing",
        case_id=case.case_id,
        seed_transaction_ids=[fraud_txns[0].transaction_id],
        fraud_transaction_ids=[t.transaction_id for t in fraud_txns],
        fraud_accounts=[c.account_id for c in collectors],
        source_account=smurf_source.account_id,
        intended_downstream_path=[smurf_source.account_id] + [c.account_id for c in collectors],
        intended_next_hop_label={
            smurf_source.account_id: [c.account_id for c in collectors]
        },
        expected_convergence_account=None,
        injected_fraud_amount=total_amount,
        metadata={
            "chunk_count": len(fraud_txns),
            "synthetic_micro_flow_threshold_paise": synthetic_micro_flow_threshold,
            "max_chunk_amount_paise": synthetic_micro_flow_threshold,
            "average_chunk_amount_paise": total_amount // chunk_count,
        },
    )

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type="smurfing",
        transactions=fraud_txns,
        cases=[case],
        truth=truth,
        accounts=pool.all_accounts(),
    )


# ── 9. Rapid Pass-Through ─────────────────────────────────────────────────────


def generate_rapid_pass_through_scenario(
    scenario_id: str = "sc-09-rapid-pass-through",
    seed: int = 50,
    base_time: datetime | None = None,
) -> ScenarioResult:
    """Family 9: Rapid pass-through: Low dwell-time hops (sub-minute velocity)."""
    rng = random.Random(seed)
    start = base_time or datetime(2026, 10, 8, 17, 0, 0, tzinfo=UTC)
    pool = AccountPool(prefix=f"{scenario_id}-acc")

    victim = pool.new_account(AccountRole.VICTIM, "BANK_A", "Victim Account")
    hop1 = pool.new_account(AccountRole.MULE, "BANK_A", "Instant Relay Mule 1")
    hop2 = pool.new_account(AccountRole.MULE, "BANK_B", "Instant Relay Mule 2")
    hop3 = pool.new_account(AccountRole.MULE, "BANK_C", "Instant Relay Mule 3")
    cashout = pool.new_account(AccountRole.EXFILTRATION, "BANK_D", "Cashout Account")

    path = [victim, hop1, hop2, hop3, cashout]
    fraud_amount = 35_000_000  # ₹3,50,000

    # 40-second inter-hop latency
    fraud_txns = build_linear_hop_chain(
        path=path,
        initial_amount=fraud_amount,
        start_time=start,
        hop_delay_seconds=40.0,
        id_prefix=scenario_id,
        fee_percentage=0.005,
        channel=TransactionChannel.UPI,
    )

    case = create_fraud_case(
        case_id=f"case-{scenario_id}",
        title="High-Velocity Relay — Sub-Minute Dwell Time",
        description="Laundering chain moving through 4 accounts in under 3 minutes total elapsed time.",
        transaction_ids=[fraud_txns[0].transaction_id],
        opened_at=start + timedelta(minutes=5),
        origin=CaseOrigin.BANK_DETECTION,
    )

    truth = ScenarioTruth(
        scenario_id=scenario_id,
        scenario_type="rapid_pass_through",
        case_id=case.case_id,
        seed_transaction_ids=[fraud_txns[0].transaction_id],
        fraud_transaction_ids=[t.transaction_id for t in fraud_txns],
        fraud_accounts=[a.account_id for a in path[1:]],
        source_account=victim.account_id,
        intended_downstream_path=[a.account_id for a in path],
        intended_next_hop_label={
            path[i].account_id: path[i + 1].account_id for i in range(len(path) - 1)
        },
        expected_convergence_account=None,
        injected_fraud_amount=fraud_amount,
        metadata={
            "inter_hop_delay_seconds": 40.0,
            "total_dwell_seconds": 120.0,
        },
    )

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type="rapid_pass_through",
        transactions=fraud_txns,
        cases=[case],
        truth=truth,
        accounts=pool.all_accounts(),
    )


# ── 10. Benign High-Volume Merchant (Negative Control) ───────────────────────


def generate_benign_high_volume_merchant_scenario(
    scenario_id: str = "sc-10-benign-merchant",
    seed: int = 51,
    base_time: datetime | None = None,
) -> ScenarioResult:
    """Family 10: Negative control: High-degree legitimate retail merchant with dozens of clean purchases."""
    rng = random.Random(seed)
    start = base_time or datetime(2026, 10, 8, 8, 0, 0, tzinfo=UTC)
    pool = AccountPool(prefix=f"{scenario_id}-acc")

    merchant = pool.new_account(AccountRole.MERCHANT, "BANK_A", "MegaMart Retail Superstore")
    customers = [
        pool.new_account(AccountRole.LEGITIMATE, rng.choice(SYNTHETIC_BANKS), f"Customer {i+1:02d}")
        for i in range(25)
    ]
    suppliers = [
        pool.new_account(AccountRole.LEGITIMATE, "BANK_B", "Wholesale Supplier Alpha"),
        pool.new_account(AccountRole.LEGITIMATE, "BANK_C", "Logistics Fleet Partner"),
    ]

    txns: list[TransactionEvent] = []

    # 1. 30 retail customer purchases over 12 hours
    counter = 0
    total_sales = 0
    for idx in range(30):
        counter += 1
        cust = rng.choice(customers)
        amt = rng.randint(45_000, 750_000)  # ₹450 to ₹7,500
        total_sales += amt
        txn_time = start + timedelta(seconds=rng.uniform(0, 12 * 3600))

        txns.append(
            make_transaction(
                event_id=f"evt-{scenario_id}-sale{counter:03d}",
                transaction_id=f"txn-{scenario_id}-sale{counter:03d}",
                sender=cust,
                receiver=merchant,
                amount_minor_units=amt,
                occurred_at=txn_time,
                channel=TransactionChannel.UPI,
            )
        )

    # 2. Legitimate supplier disbursements
    for idx, supplier in enumerate(suppliers):
        counter += 1
        amt = rng.randint(2_500_000, 5_000_000)  # ₹25,000 to ₹50,000
        txn_time = start + timedelta(hours=14 + idx)
        txns.append(
            make_transaction(
                event_id=f"evt-{scenario_id}-payout{counter:03d}",
                transaction_id=f"txn-{scenario_id}-payout{counter:03d}",
                sender=merchant,
                receiver=supplier,
                amount_minor_units=amt,
                occurred_at=txn_time,
                channel=TransactionChannel.NEFT,
            )
        )

    txns.sort(key=lambda t: t.occurred_at)

    # Negative control: ZERO fraud injected, NO fraud case
    truth = ScenarioTruth(
        scenario_id=scenario_id,
        scenario_type="benign_high_volume_merchant",
        case_id=None,
        seed_transaction_ids=[],
        fraud_transaction_ids=[],
        fraud_accounts=[],
        source_account=None,
        intended_downstream_path=[],
        intended_next_hop_label={},
        expected_convergence_account=None,
        injected_fraud_amount=0,
        metadata={
            "merchant_account": merchant.account_id,
            "total_legitimate_sales_paise": total_sales,
            "transaction_count": len(txns),
            "is_negative_control": True,
        },
    )

    return ScenarioResult(
        scenario_id=scenario_id,
        scenario_type="benign_high_volume_merchant",
        transactions=txns,
        cases=[],
        truth=truth,
        accounts=pool.all_accounts(),
    )


# ── Scenario Registry ─────────────────────────────────────────────────────────

SCENARIO_GENERATORS = {
    "simple_chain": generate_simple_chain_scenario,
    "fan_out": generate_fan_out_scenario,
    "fan_in": generate_fan_in_scenario,
    "fan_out_fan_in": generate_fan_out_fan_in_scenario,
    "commingling": generate_commingling_scenario,
    "cold_start": generate_cold_start_scenario,
    "cross_bank": generate_cross_bank_scenario,
    "smurfing": generate_smurfing_scenario,
    "rapid_pass_through": generate_rapid_pass_through_scenario,
    "benign_high_volume_merchant": generate_benign_high_volume_merchant_scenario,
}
