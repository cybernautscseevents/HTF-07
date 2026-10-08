"""
AEGIS-Flow Synthetic Generator — Fraud Primitives Module
=========================================================

Core primitives for constructing illicit transaction movements:
- Linear hop chains with parameterized inter-hop velocity
- Fan-out dispersion (splitting tainted funds across multiple mules)
- Fan-in consolidation (aggregating multiple feeder flows)
- Smurfing / structuring (breaking large sums into deliberately small micro-transactions)
- Case construction conforming to canonical FraudCase schema
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Sequence

from contracts.account import AccountReference
from contracts.case import FraudCase
from contracts.enums import CaseOrigin, CaseStatus, TransactionChannel, TransactionStatus
from contracts.transaction import TransactionEvent
from scripts.generator.legitimate import make_transaction

UTC = timezone.utc


def create_fraud_case(
    case_id: str,
    title: str,
    description: str,
    transaction_ids: list[str],
    opened_at: datetime,
    origin: CaseOrigin = CaseOrigin.SYNTHETIC,
    status: CaseStatus = CaseStatus.OPEN,
) -> FraudCase:
    """Create a canonical FraudCase container linked to specific transactions."""
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=UTC)

    return FraudCase(
        case_id=case_id,
        title=title,
        description=description,
        origin=origin,
        status=status,
        transaction_ids=list(transaction_ids),
        opened_at=opened_at,
        updated_at=opened_at + timedelta(minutes=5),
    )


def build_linear_hop_chain(
    path: Sequence[AccountReference],
    initial_amount: int,
    start_time: datetime,
    hop_delay_seconds: float,
    id_prefix: str,
    fee_percentage: float = 0.01,  # 1% retained by mule
    channel: TransactionChannel = TransactionChannel.UPI,
) -> list[TransactionEvent]:
    """Generate a sequential chain of transactions through an ordered account path.

    path: [Source/Victim, Mule1, Mule2, ..., Cashout]
    """
    if len(path) < 2:
        return []

    events: list[TransactionEvent] = []
    current_time = start_time
    current_amount = initial_amount

    for idx in range(len(path) - 1):
        sender = path[idx]
        receiver = path[idx + 1]

        # Calculate transfer amount (slight deduction for mule fee after hop 1)
        if idx > 0 and fee_percentage > 0:
            deduction = int(current_amount * fee_percentage)
            current_amount = max(1000, current_amount - deduction)

        evt_id = f"evt-{id_prefix}-hop{idx+1:02d}"
        txn_id = f"txn-{id_prefix}-hop{idx+1:02d}"

        events.append(
            make_transaction(
                event_id=evt_id,
                transaction_id=txn_id,
                sender=sender,
                receiver=receiver,
                amount_minor_units=current_amount,
                occurred_at=current_time,
                channel=channel,
                observed_latency_seconds=1.5,
            )
        )

        current_time += timedelta(seconds=hop_delay_seconds)

    return events


def build_fan_out_split(
    source: AccountReference,
    mules: Sequence[AccountReference],
    total_amount: int,
    start_time: datetime,
    id_prefix: str,
    channel: TransactionChannel = TransactionChannel.UPI,
    time_jitter_seconds: float = 30.0,
    rng: random.Random | None = None,
) -> list[TransactionEvent]:
    """Split a source amount across multiple mule recipients."""
    if not mules:
        return []

    r = rng or random.Random(42)
    n = len(mules)
    base_split = total_amount // n
    remainder = total_amount % n

    events: list[TransactionEvent] = []
    for idx, mule in enumerate(mules):
        amt = base_split + (remainder if idx == 0 else 0)
        jitter = r.uniform(0, time_jitter_seconds)
        txn_time = start_time + timedelta(seconds=jitter)

        evt_id = f"evt-{id_prefix}-split{idx+1:02d}"
        txn_id = f"txn-{id_prefix}-split{idx+1:02d}"

        events.append(
            make_transaction(
                event_id=evt_id,
                transaction_id=txn_id,
                sender=source,
                receiver=mule,
                amount_minor_units=amt,
                occurred_at=txn_time,
                channel=channel,
            )
        )

    events.sort(key=lambda e: e.occurred_at)
    return events


def build_fan_in_consolidation(
    feeders: Sequence[AccountReference],
    aggregator: AccountReference,
    amounts: Sequence[int],
    start_time: datetime,
    id_prefix: str,
    channel: TransactionChannel = TransactionChannel.IMPS,
    time_window_seconds: float = 600.0,
    rng: random.Random | None = None,
) -> list[TransactionEvent]:
    """Consolidate multiple incoming transfers into an aggregator account."""
    if len(feeders) != len(amounts) or not feeders:
        return []

    r = rng or random.Random(42)
    events: list[TransactionEvent] = []

    for idx, (feeder, amt) in enumerate(zip(feeders, amounts)):
        offset = r.uniform(0, time_window_seconds)
        txn_time = start_time + timedelta(seconds=offset)

        evt_id = f"evt-{id_prefix}-join{idx+1:02d}"
        txn_id = f"txn-{id_prefix}-join{idx+1:02d}"

        events.append(
            make_transaction(
                event_id=evt_id,
                transaction_id=txn_id,
                sender=feeder,
                receiver=aggregator,
                amount_minor_units=amt,
                occurred_at=txn_time,
                channel=channel,
            )
        )

    events.sort(key=lambda e: e.occurred_at)
    return events


def build_smurfing_transfers(
    sender: AccountReference,
    receivers: Sequence[AccountReference],
    total_amount: int,
    chunk_count: int,
    max_chunk_amount: int,
    start_time: datetime,
    time_span_seconds: float,
    id_prefix: str,
    rng: random.Random,
    channel: TransactionChannel = TransactionChannel.UPI,
) -> list[TransactionEvent]:
    """Break total_amount into chunk_count small transfers strictly below max_chunk_amount (configurable benchmark threshold)."""
    if chunk_count <= 0 or not receivers:
        return []

    # Ensure total_amount can physically fit within chunk_count * (max_chunk_amount - 1000)
    upper_bound = max_chunk_amount - 1000
    min_chunk = 50_000  # ₹500
    assert total_amount <= chunk_count * upper_bound, "total_amount too large for chunk_count"

    # Start with uniform split
    base_chunk = total_amount // chunk_count
    remainder = total_amount % chunk_count
    chunks = [base_chunk + (1 if i < remainder else 0) for i in range(chunk_count)]

    # Deterministically jitter pairs while strictly preserving sum and bounds
    for _ in range(chunk_count * 10):
        i = rng.randint(0, chunk_count - 1)
        j = rng.randint(0, chunk_count - 1)
        if i == j:
            continue
        max_shift_up = upper_bound - chunks[i]
        max_shift_down = chunks[j] - min_chunk
        max_shift = min(max_shift_up, max_shift_down)
        if max_shift > 5000:
            shift = rng.randint(1000, max_shift)
            chunks[i] += shift
            chunks[j] -= shift

    events: list[TransactionEvent] = []
    for idx, chunk_amt in enumerate(chunks):
        receiver = receivers[idx % len(receivers)]
        offset = (time_span_seconds / max(1, chunk_count)) * idx + rng.uniform(0, 10.0)
        txn_time = start_time + timedelta(seconds=offset)

        evt_id = f"evt-{id_prefix}-smurf{idx+1:03d}"
        txn_id = f"txn-{id_prefix}-smurf{idx+1:03d}"

        events.append(
            make_transaction(
                event_id=evt_id,
                transaction_id=txn_id,
                sender=sender,
                receiver=receiver,
                amount_minor_units=chunk_amt,
                occurred_at=txn_time,
                channel=channel,
            )
        )

    events.sort(key=lambda e: e.occurred_at)
    return events
