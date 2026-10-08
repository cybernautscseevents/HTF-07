"""
Shared fixtures for graph engine tests.

All fixtures use canonical TransactionEvent from the frozen contract.
No duplicate event schemas are created.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contracts.account import AccountReference
from contracts.enums import (
    EventOrigin,
    TransactionChannel,
    TransactionStatus,
)
from contracts.transaction import TransactionEvent

UTC = timezone.utc
T0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)


def make_event(
    event_id: str,
    transaction_id: str,
    sender_id: str,
    receiver_id: str,
    *,
    amount: int = 100_00,
    currency: str = "INR",
    occurred_at: datetime | None = None,
    observed_at: datetime | None = None,
    status: TransactionStatus = TransactionStatus.COMPLETED,
    channel: TransactionChannel = TransactionChannel.UPI,
    origin: EventOrigin = EventOrigin.SYNTHETIC,
    sender_institution: str | None = None,
    receiver_institution: str | None = None,
) -> TransactionEvent:
    """Factory for canonical TransactionEvent test fixtures."""
    if occurred_at is None:
        occurred_at = T0
    if observed_at is None:
        observed_at = occurred_at + timedelta(seconds=1)

    return TransactionEvent(
        event_id=event_id,
        transaction_id=transaction_id,
        sender=AccountReference(
            account_id=sender_id, institution=sender_institution,
        ),
        receiver=AccountReference(
            account_id=receiver_id, institution=receiver_institution,
        ),
        amount_minor_units=amount,
        currency=currency,
        occurred_at=occurred_at,
        observed_at=observed_at,
        status=status,
        channel=channel,
        origin=origin,
    )


# ── Pre-built topologies ─────────────────────────────────────────────────────


def chain_events() -> list[TransactionEvent]:
    """A → B → C → D  (strictly increasing time)."""
    return [
        make_event("e1", "t1", "A", "B", occurred_at=T0 + timedelta(minutes=0)),
        make_event("e2", "t2", "B", "C", occurred_at=T0 + timedelta(minutes=10)),
        make_event("e3", "t3", "C", "D", occurred_at=T0 + timedelta(minutes=20)),
    ]


def fan_out_events() -> list[TransactionEvent]:
    """S fans out to A, B, C within 5 minutes."""
    return [
        make_event("fo1", "tf1", "S", "A", occurred_at=T0 + timedelta(minutes=0)),
        make_event("fo2", "tf2", "S", "B", occurred_at=T0 + timedelta(minutes=1)),
        make_event("fo3", "tf3", "S", "C", occurred_at=T0 + timedelta(minutes=2)),
    ]


def fan_in_events() -> list[TransactionEvent]:
    """A, B, C all send to T within 5 minutes."""
    return [
        make_event("fi1", "ti1", "A", "T", occurred_at=T0 + timedelta(minutes=0)),
        make_event("fi2", "ti2", "B", "T", occurred_at=T0 + timedelta(minutes=1)),
        make_event("fi3", "ti3", "C", "T", occurred_at=T0 + timedelta(minutes=2)),
    ]


def pass_through_events() -> list[TransactionEvent]:
    """A → P at T0, P → B at T0+30s  (rapid pass-through)."""
    return [
        make_event("pt1", "tp1", "A", "P", occurred_at=T0),
        make_event("pt2", "tp2", "P", "B", occurred_at=T0 + timedelta(seconds=30)),
    ]


def fan_out_fan_in_events() -> list[TransactionEvent]:
    """S → I1, I2, I3  then  I1 → T, I2 → T, I3 → T."""
    return [
        # Fan-out from S
        make_event("fofi1", "tfofi1", "S", "I1", occurred_at=T0 + timedelta(minutes=0)),
        make_event("fofi2", "tfofi2", "S", "I2", occurred_at=T0 + timedelta(minutes=1)),
        make_event("fofi3", "tfofi3", "S", "I3", occurred_at=T0 + timedelta(minutes=2)),
        # Fan-in to T
        make_event("fofi4", "tfofi4", "I1", "T", occurred_at=T0 + timedelta(minutes=10)),
        make_event("fofi5", "tfofi5", "I2", "T", occurred_at=T0 + timedelta(minutes=11)),
        make_event("fofi6", "tfofi6", "I3", "T", occurred_at=T0 + timedelta(minutes=12)),
    ]


def mixed_status_events() -> list[TransactionEvent]:
    """Events with various statuses for active-flow filtering tests."""
    return [
        make_event("ms1", "tm1", "A", "B", occurred_at=T0,
                    status=TransactionStatus.COMPLETED),
        make_event("ms2", "tm2", "A", "C", occurred_at=T0 + timedelta(minutes=1),
                    status=TransactionStatus.PENDING),
        make_event("ms3", "tm3", "A", "D", occurred_at=T0 + timedelta(minutes=2),
                    status=TransactionStatus.FAILED),
        make_event("ms4", "tm4", "A", "E", occurred_at=T0 + timedelta(minutes=3),
                    status=TransactionStatus.REVERSED),
        make_event("ms5", "tm5", "A", "F", occurred_at=T0 + timedelta(minutes=4),
                    status=TransactionStatus.COMPLETED),
    ]
