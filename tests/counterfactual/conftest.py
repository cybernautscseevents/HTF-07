"""Shared fixtures for counterfactual simulation tests.

Uses canonical TransactionEvent from the frozen contract.
Mirrors the taint test conftest pattern.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.taint.engine import TaintEngine
from backend.app.taint.models import TaintResult, TaintSeed
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


def run_taint(
    graph: TemporalGraph, seeds: list[TaintSeed]
) -> TaintResult:
    return TaintEngine().run(graph, seeds)


# ── Pre-built topologies ─────────────────────────────────────────────────────


def simple_chain_events() -> list[TransactionEvent]:
    """A → B → C → D  (strictly increasing time, 10-minute intervals).

    Seed at A→B (100_00 fully tainted).
    """
    return [
        make_event("e1", "A", "B", 100_00, 0),
        make_event("e2", "B", "C", 100_00, 10),
        make_event("e3", "C", "D", 100_00, 20),
    ]


def fan_out_events() -> list[TransactionEvent]:
    """A → B, A → C, A → D  (fan-out from A).

    Seed at external→A (300_00), then A fans out.
    """
    return [
        make_event("seed1", "EXT", "A", 300_00, 0),
        make_event("fo1", "A", "B", 100_00, 10),
        make_event("fo2", "A", "C", 100_00, 11),
        make_event("fo3", "A", "D", 100_00, 12),
    ]


def fan_in_events() -> list[TransactionEvent]:
    """B, C, D → T  (fan-in to T).

    Three separate seeds, each 100_00 tainted.
    """
    return [
        make_event("seed_b", "EXT_B", "B", 100_00, 0, transaction_id="tx-seed-b"),
        make_event("seed_c", "EXT_C", "C", 100_00, 1, transaction_id="tx-seed-c"),
        make_event("seed_d", "EXT_D", "D", 100_00, 2, transaction_id="tx-seed-d"),
        make_event("fi1", "B", "T", 100_00, 10),
        make_event("fi2", "C", "T", 100_00, 11),
        make_event("fi3", "D", "T", 100_00, 12),
    ]


def fan_out_fan_in_events() -> list[TransactionEvent]:
    """S → I1, I2, I3 → T  (fan-out then fan-in).

    Seed at EXT→S (300_00 fully tainted).
    """
    return [
        make_event("seed_s", "EXT", "S", 300_00, 0),
        make_event("fofi1", "S", "I1", 100_00, 10),
        make_event("fofi2", "S", "I2", 100_00, 11),
        make_event("fofi3", "S", "I3", 100_00, 12),
        make_event("fofi4", "I1", "T", 100_00, 20),
        make_event("fofi5", "I2", "T", 100_00, 21),
        make_event("fofi6", "I3", "T", 100_00, 22),
    ]


def commingling_events() -> list[TransactionEvent]:
    """Commingling: B receives tainted from A and clean from LEGIT,
    then forwards a commingled amount.

    Seed at EXT→A (100_00 tainted).  LEGIT→B (200_00 clean, separate tx).
    Then B→C (300_00 commingled).
    """
    return [
        make_event("seed_a", "EXT", "A", 100_00, 0),
        make_event("e_ab", "A", "B", 100_00, 10),
        make_event("e_lb", "LEGIT", "B", 200_00, 11),
        make_event("e_bc", "B", "C", 300_00, 20),
    ]


def multi_branch_events() -> list[TransactionEvent]:
    """Multiple branches from a hub:

    Seed at EXT→HUB (400_00 tainted).
    HUB → B1 (100_00)
    HUB → B2 (100_00)
    B1  → C1 (100_00)
    B2  → C2 (100_00)
    HUB → B3 (200_00)
    """
    return [
        make_event("seed_hub", "EXT", "HUB", 400_00, 0),
        make_event("h_b1", "HUB", "B1", 100_00, 10),
        make_event("h_b2", "HUB", "B2", 100_00, 11),
        make_event("b1_c1", "B1", "C1", 100_00, 20),
        make_event("b2_c2", "B2", "C2", 100_00, 21),
        make_event("h_b3", "HUB", "B3", 200_00, 30),
    ]
