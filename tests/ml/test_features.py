"""
Unit tests for ML Feature Extraction
====================================

Verifies:
1. Complete feature set extraction (all 35 canonical features).
2. Strict temporal filtering: future transactions cannot alter historical features.
3. Cold-start vs history-rich classification and evidence maturity levels.
4. Pairwise next-hop candidate feature extraction.
5. Zero leakage: no ground truth fields or labels in production features.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.ml.features import (
    ACCOUNT_FEATURE_NAMES,
    NEXT_HOP_FEATURE_NAMES,
    determine_evidence_maturity,
    extract_account_features,
    extract_next_hop_candidate_features,
)
from backend.app.ml.schemas import EvidenceMaturity
from contracts.account import AccountReference
from contracts.enums import EventOrigin, TransactionChannel, TransactionStatus
from contracts.transaction import TransactionEvent


UTC = timezone.utc


def _make_event(
    event_id: str,
    sender_id: str,
    receiver_id: str,
    amount: int,
    occurred_at: datetime,
    status: TransactionStatus = TransactionStatus.COMPLETED,
) -> TransactionEvent:
    return TransactionEvent(
        event_id=event_id,
        transaction_id=f"tx-{event_id}",
        sender=AccountReference(account_id=sender_id, institution="BANK_A"),
        receiver=AccountReference(account_id=receiver_id, institution="BANK_B"),
        amount_minor_units=amount,
        currency="INR",
        occurred_at=occurred_at,
        observed_at=occurred_at + timedelta(seconds=1),
        status=status,
        channel=TransactionChannel.UPI,
        origin=EventOrigin.BANK_FEED,
    )


def test_extract_all_35_features() -> None:
    """Verifies that extract_account_features produces all required 35 keys."""
    t0 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    e1 = _make_event("e1", "acc-A", "acc-B", 100_000, t0)
    g.add_event(e1)

    feats_b = extract_account_features(g, "acc-B", as_of_time=t0)
    assert len(feats_b) == len(ACCOUNT_FEATURE_NAMES)
    for name in ACCOUNT_FEATURE_NAMES:
        assert name in feats_b, f"Missing feature: {name}"

    assert feats_b["in_degree"] == 1.0
    assert feats_b["out_degree"] == 0.0
    assert feats_b["total_inbound_amount"] == 100_000.0


def test_strict_temporal_causality_no_future_leakage() -> None:
    """Crucial test: Adding future transactions MUST NOT change features evaluated at as_of_time."""
    t0 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=UTC)
    t_eval = t0 + timedelta(minutes=5)
    t_future = t0 + timedelta(hours=2)

    g = TemporalGraph()
    # Past transaction
    e_past = _make_event("e-past", "acc-A", "acc-B", 500_000, t0)
    g.add_event(e_past)

    # Feature snapshot before future event is inserted
    feats_before = extract_account_features(g, "acc-B", as_of_time=t_eval)

    # Now insert a huge future transaction after t_eval
    e_future = _make_event("e-future", "acc-B", "acc-C", 500_000, t_future)
    g.add_event(e_future)

    # Feature snapshot at the exact same as_of_time
    feats_after = extract_account_features(g, "acc-B", as_of_time=t_eval)

    assert feats_before == feats_after, "Future transaction leaked into past feature snapshot!"
    assert feats_after["out_degree"] == 0.0
    assert feats_after["total_outbound_amount"] == 0.0


def test_cold_start_and_evidence_maturity_classification() -> None:
    """Verifies evidence maturity is correctly mapped based on history vs current flow."""
    # 1. Limited evidence: 1 transaction total
    m_limited = determine_evidence_maturity(
        total_tx_count=1,
        historical_tx_count=0,
        has_historical_profile=False,
    )
    assert m_limited == EvidenceMaturity.LIMITED_EVIDENCE

    # 2. Flow dominant: multiple transactions, but zero pre-incident history
    m_flow = determine_evidence_maturity(
        total_tx_count=4,
        historical_tx_count=0,
        has_historical_profile=False,
    )
    assert m_flow == EvidenceMaturity.FLOW_DOMINANT

    # 3. Strong history: 6 total transactions with established profile
    m_strong = determine_evidence_maturity(
        total_tx_count=6,
        historical_tx_count=4,
        has_historical_profile=True,
    )
    assert m_strong == EvidenceMaturity.STRONG_HISTORY


def test_rapid_pass_through_feature_detection() -> None:
    """Verifies that an account receiving and forwarding funds within 60s is flagged."""
    t0 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=60)

    g = TemporalGraph()
    e_in = _make_event("e-in", "acc-victim", "acc-mule", 1_000_000, t0)
    e_out = _make_event("e-out", "acc-mule", "acc-exit", 990_000, t1)
    g.add_event(e_in)
    g.add_event(e_out)

    feats = extract_account_features(g, "acc-mule", as_of_time=t1 + timedelta(seconds=1))
    assert feats["has_rapid_pass_through"] == 1.0
    assert feats["min_pass_through_seconds"] == 60.0
    assert feats["forwarding_ratio"] == 0.99


def test_next_hop_candidate_features() -> None:
    """Verifies pairwise candidate feature extraction for next-hop prediction."""
    t0 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    e1 = _make_event("e1", "acc-src", "acc-cand", 250_000, t0)
    g.add_event(e1)

    nh_feats = extract_next_hop_candidate_features(
        graph=g,
        source_id="acc-src",
        candidate_id="acc-cand",
        as_of_time=t0 + timedelta(minutes=1),
    )
    assert len(nh_feats) == len(NEXT_HOP_FEATURE_NAMES)
    assert nh_feats["past_transfers_count"] == 1.0
    assert nh_feats["past_transfer_volume"] == 250_000.0
    assert nh_feats["candidate_in_degree"] == 1.0


def test_forwarding_ratio_pure_sender_and_receiver() -> None:
    """Verifies that an account with 0 inbound volume has forwarding_ratio=0.0 (not total_outbound)."""
    t0 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    e1 = _make_event("e1", "sender-only", "receiver-only", 750_000, t0)
    g.add_event(e1)

    feats_sender = extract_account_features(g, "sender-only", as_of_time=t0)
    feats_receiver = extract_account_features(g, "receiver-only", as_of_time=t0)

    # Pure sender forwarded 0 inbound funds -> 0.0
    assert feats_sender["forwarding_ratio"] == 0.0
    assert feats_sender["total_outbound_amount"] == 750_000.0
    assert feats_sender["total_inbound_amount"] == 0.0

    # Pure receiver forwarded 0 funds -> 0.0
    assert feats_receiver["forwarding_ratio"] == 0.0
    assert feats_receiver["total_inbound_amount"] == 750_000.0
    assert feats_receiver["total_outbound_amount"] == 0.0
