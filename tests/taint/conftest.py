"""Fixtures for deterministic taint-engine tests using canonical events."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.graph.temporal_graph import TemporalGraph
from contracts.account import AccountReference
from contracts.enums import EventOrigin, TransactionChannel, TransactionStatus
from contracts.transaction import TransactionEvent

UTC = timezone.utc
T0 = datetime(2026, 10, 9, 9, 0, 0, tzinfo=UTC)


def make_event(
    event_id: str,
    sender_id: str,
    receiver_id: str,
    amount: int,
    minutes: int,
    *,
    transaction_id: str | None = None,
    status: TransactionStatus = TransactionStatus.COMPLETED,
) -> TransactionEvent:
    occurred_at = T0 + timedelta(minutes=minutes)
    return TransactionEvent(
        event_id=event_id,
        transaction_id=transaction_id or f"tx-{event_id}",
        sender=AccountReference(account_id=sender_id, institution="BANK_A"),
        receiver=AccountReference(account_id=receiver_id, institution="BANK_B"),
        amount_minor_units=amount,
        currency="INR",
        occurred_at=occurred_at,
        observed_at=occurred_at + timedelta(seconds=1),
        status=status,
        channel=TransactionChannel.UPI,
        origin=EventOrigin.SYNTHETIC,
    )


def make_graph(*events: TransactionEvent) -> TemporalGraph:
    graph = TemporalGraph()
    for event in events:
        graph.add_event(event)
    return graph
