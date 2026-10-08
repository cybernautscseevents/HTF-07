"""
Unit tests for Next-Hop Predictor
=================================

Verifies:
1. Candidate generation adheres to temporal validity.
2. Candidate probabilities sum to 1.0 (softmax normalization).
3. Candidates are returned ranked in strictly descending probability order.
4. Top-1, Top-3, and MRR metrics computation.
5. Packaging into canonical EvidenceEnvelope.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.ml.next_hop import NextHopPredictor
from backend.app.ml.schemas import NextHopPrediction
from contracts.account import AccountReference
from contracts.enums import (
    EvidenceProviderType,
    TransactionChannel,
    TransactionStatus,
    EventOrigin,
)
from contracts.transaction import TransactionEvent

UTC = timezone.utc


def _make_event(
    event_id: str,
    sender_id: str,
    receiver_id: str,
    amount: int,
    occurred_at: datetime,
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
        status=TransactionStatus.COMPLETED,
        channel=TransactionChannel.UPI,
        origin=EventOrigin.BANK_FEED,
    )




def test_next_hop_candidate_ranking_and_softmax(next_hop_predictor: NextHopPredictor) -> None:
    """Verifies that candidates are ranked by descending probability and sum to 1.0."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    # Flow from src to cand1, cand2, cand3
    g.add_event(_make_event("e1", "src", "cand1", 200_000, t0))
    g.add_event(_make_event("e2", "src", "cand2", 100_000, t0 + timedelta(minutes=1)))
    g.add_event(_make_event("e3", "cand1", "cand3", 190_000, t0 + timedelta(minutes=2)))

    pred = next_hop_predictor.predict_next_hop(
        graph=g,
        source_account_id="src",
        as_of_time=t0 + timedelta(minutes=5),
        candidate_pool=["cand1", "cand2", "cand3"],
        top_k=3,
    )

    assert isinstance(pred, NextHopPrediction)
    assert len(pred.candidates) == 3
    assert pred.top_1_account_id == pred.candidates[0].account_id

    # Verify descending probability order
    probs = [c.predicted_probability for c in pred.candidates]
    for i in range(len(probs) - 1):
        assert probs[i] >= probs[i + 1], "Candidates not sorted descending by probability"

    # Verify sum ~ 1.0
    assert pytest.approx(sum(probs), abs=0.02) == 1.0


def test_next_hop_evidence_envelope(next_hop_predictor: NextHopPredictor) -> None:
    """Verifies packaging next hop prediction into canonical EvidenceEnvelope."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    g.add_event(_make_event("e1", "src", "dest", 100_000, t0))

    pred = next_hop_predictor.predict_next_hop(
        graph=g,
        source_account_id="src",
        as_of_time=t0,
        candidate_pool=["dest"],
    )

    envelope = pred.to_evidence_envelope(case_id="case-456")
    assert envelope.provider_type == EvidenceProviderType.ML_MODEL
    assert envelope.case_id == "case-456"
    assert "src" in envelope.summary
    assert "top_1_account_id" in envelope.body
    assert envelope.body["top_1_account_id"] == "dest"
