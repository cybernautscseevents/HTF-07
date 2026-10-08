"""
AEGIS-Flow Synthetic Generator — Legitimate & Decoy Transactions Module
========================================================================

Constructs canonical TransactionEvent objects for benign background activity,
including:
- Decoy transactions around mule/victim nodes to introduce natural graph noise
- Historical transactions preceding fraud events (for established accounts)
- Clean business inflows for commingling tests
- High-volume customer purchases for benign merchant baselines
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Sequence

from contracts.account import AccountReference
from contracts.enums import EventOrigin, TransactionChannel, TransactionStatus
from contracts.transaction import TransactionEvent

UTC = timezone.utc


def make_transaction(
    event_id: str,
    transaction_id: str,
    sender: AccountReference,
    receiver: AccountReference,
    amount_minor_units: int,
    occurred_at: datetime,
    observed_latency_seconds: float = 2.0,
    channel: TransactionChannel = TransactionChannel.UPI,
    status: TransactionStatus = TransactionStatus.COMPLETED,
    reference: str | None = None,
) -> TransactionEvent:
    """Factory creating a valid canonical TransactionEvent."""
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)

    observed_at = occurred_at + timedelta(seconds=max(0.1, observed_latency_seconds))
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)

    ref = reference or f"SYNTH-UTR-{transaction_id.upper()}"

    return TransactionEvent(
        event_id=event_id,
        transaction_id=transaction_id,
        reference=ref,
        sender=sender,
        receiver=receiver,
        amount_minor_units=amount_minor_units,
        currency="INR",
        occurred_at=occurred_at,
        observed_at=observed_at,
        status=status,
        channel=channel,
        origin=EventOrigin.SYNTHETIC,
    )


def generate_decoy_transactions(
    accounts: Sequence[AccountReference],
    external_counterparties: Sequence[AccountReference],
    start_time: datetime,
    end_time: datetime,
    count: int,
    rng: random.Random,
    id_prefix: str = "decoy",
) -> list[TransactionEvent]:
    """Generate realistic decoy transactions between scenario accounts and external parties."""
    if not accounts or not external_counterparties or count <= 0:
        return []

    events: list[TransactionEvent] = []
    time_span = max(1.0, (end_time - start_time).total_seconds())

    # Typical daily personal spending amounts in paise (₹150 to ₹8,500)
    common_amounts = [
        15000,   # ₹150 (coffee / snack)
        35000,   # ₹350 (cab / commute)
        79900,   # ₹799 (subscription / telecom)
        125000,  # ₹1,250 (groceries)
        249900,  # ₹2,499 (retail / apparel)
        450000,  # ₹4,500 (utilities / bill)
        850000,  # ₹8,500 (electronics / dining)
    ]

    channels = [
        TransactionChannel.UPI,
        TransactionChannel.UPI,
        TransactionChannel.UPI,
        TransactionChannel.CARD,
        TransactionChannel.IMPS,
    ]

    for idx in range(count):
        internal_acct = rng.choice(accounts)
        external_acct = rng.choice(external_counterparties)

        # 60% outgoing spending, 40% incoming benign funds
        if rng.random() < 0.6:
            sender, receiver = internal_acct, external_acct
        else:
            sender, receiver = external_acct, internal_acct

        amount = rng.choice(common_amounts) + rng.randint(-2000, 2000)
        amount = max(5000, amount)  # minimum ₹50

        offset_seconds = rng.uniform(0, time_span)
        txn_time = start_time + timedelta(seconds=offset_seconds)
        channel = rng.choice(channels)

        evt_id = f"evt-{id_prefix}-{idx+1:04d}"
        txn_id = f"txn-{id_prefix}-{idx+1:04d}"

        events.append(
            make_transaction(
                event_id=evt_id,
                transaction_id=txn_id,
                sender=sender,
                receiver=receiver,
                amount_minor_units=amount,
                occurred_at=txn_time,
                channel=channel,
                observed_latency_seconds=rng.uniform(0.5, 4.0),
            )
        )

    # Return events sorted deterministically by timestamp
    events.sort(key=lambda e: e.occurred_at)
    return events


def generate_historical_profile(
    established_accounts: Sequence[AccountReference],
    benchmark_parties: Sequence[AccountReference],
    cutoff_time: datetime,
    history_days: int,
    txns_per_account: int,
    rng: random.Random,
    id_prefix: str = "hist",
) -> list[TransactionEvent]:
    """Generate historical transaction activity strictly preceding cutoff_time.

    Used to establish transaction history for regular accounts, ensuring cold-start
    accounts (which are excluded from this function) have no events prior to cutoff_time.
    """
    if not established_accounts or not benchmark_parties:
        return []

    events: list[TransactionEvent] = []
    start_time = cutoff_time - timedelta(days=history_days)
    total_seconds = (cutoff_time - start_time).total_seconds() - 60  # stop at least 60s before cutoff

    counter = 0
    for acct in established_accounts:
        for _ in range(txns_per_account):
            counter += 1
            other = rng.choice(benchmark_parties)
            is_outflow = rng.random() < 0.5
            sender = acct if is_outflow else other
            receiver = other if is_outflow else acct

            amount = rng.randint(20000, 500000)  # ₹200 to ₹5,000
            offset = rng.uniform(0, total_seconds)
            txn_time = start_time + timedelta(seconds=offset)

            events.append(
                make_transaction(
                    event_id=f"evt-{id_prefix}-{counter:05d}",
                    transaction_id=f"txn-{id_prefix}-{counter:05d}",
                    sender=sender,
                    receiver=receiver,
                    amount_minor_units=amount,
                    occurred_at=txn_time,
                    channel=rng.choice([TransactionChannel.UPI, TransactionChannel.IMPS]),
                )
            )

    events.sort(key=lambda e: e.occurred_at)
    return events
