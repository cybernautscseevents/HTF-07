"""
Unit tests for Mule Risk Model
==============================

Verifies:
1. Risk score is strictly bounded in [0.0, 1.0].
2. Confidence score is strictly bounded in [0.0, 1.0].
3. Deterministic inference and reproducible predictions.
4. Model serialization and deserialization (save and load).
5. Explainability summaries and structured signal generation.
6. Packaging into canonical EvidenceEnvelope.
7. Benign merchant vs high-velocity mule discrimination.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

import numpy as np
import pytest

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.ml.features import ACCOUNT_FEATURE_NAMES, extract_account_features
from backend.app.ml.risk_model import MuleRiskModel
from backend.app.ml.schemas import AccountRiskPrediction, EvidenceMaturity
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




def test_risk_score_and_confidence_bounds(trained_risk_model: MuleRiskModel) -> None:
    """Confirms that risk_score and confidence are always in [0.0, 1.0]."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    e1 = _make_event("e1", "victim", "mule", 100_000, t0)
    e2 = _make_event("e2", "mule", "cashout", 98_000, t0 + timedelta(seconds=90))
    g.add_event(e1)
    g.add_event(e2)

    pred = trained_risk_model.predict_risk(
        graph=g,
        account_id="mule",
        as_of_time=t0 + timedelta(minutes=5),
    )

    assert isinstance(pred, AccountRiskPrediction)
    assert 0.0 <= pred.risk_score <= 1.0
    assert 0.0 <= pred.confidence <= 1.0
    assert pred.evidence_maturity in [EvidenceMaturity.FLOW_DOMINANT, EvidenceMaturity.LIMITED_EVIDENCE, EvidenceMaturity.STRONG_HISTORY]
    assert len(pred.evidence_summary) > 0


def test_model_serialization(trained_risk_model: MuleRiskModel) -> None:
    """Verifies that model save and load roundtrip produces identical predictions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "test_model.joblib"
        trained_risk_model.save(tmp_path)
        assert tmp_path.exists()

        loaded = MuleRiskModel.load(tmp_path)
        dummy_row = np.zeros((1, len(ACCOUNT_FEATURE_NAMES)), dtype=np.float32)
        p1 = trained_risk_model.predict_proba(dummy_row)
        p2 = loaded.predict_proba(dummy_row)

        np.testing.assert_allclose(p1, p2, atol=1e-6)


def test_to_canonical_evidence_envelope(trained_risk_model: MuleRiskModel) -> None:
    """Verifies packaging into canonical EvidenceEnvelope contract."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    e1 = _make_event("e1", "src", "target", 100_000, t0)
    g.add_event(e1)

    pred = trained_risk_model.predict_risk(
        graph=g,
        account_id="target",
        as_of_time=t0,
    )

    envelope = pred.to_evidence_envelope(case_id="case-123")
    assert envelope.provider_type == EvidenceProviderType.ML_MODEL
    assert envelope.case_id == "case-123"
    assert "target" in envelope.summary
    assert "risk_score" in envelope.body
    assert envelope.body["risk_score"] == pred.risk_score
    assert envelope.schema_version == "1.0.0"


def test_benign_pattern_has_low_risk(trained_risk_model: MuleRiskModel) -> None:
    """Verifies that an account that receives funds from multiple customers without immediate pass-through is low risk."""
    t0 = datetime(2026, 10, 8, 8, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    # 5 customer purchases into merchant over 6 hours, 0 forwarded out
    for i in range(5):
        e = _make_event(f"e-sale-{i}", f"cust-{i}", "retail-merchant", 50_000, t0 + timedelta(hours=i))
        g.add_event(e)

    pred = trained_risk_model.predict_risk(
        graph=g,
        account_id="retail-merchant",
        as_of_time=t0 + timedelta(hours=7),
    )
    # Forwarding ratio is 0.0, no rapid pass-through -> risk score should be well below 0.50
    assert pred.risk_score < 0.35, f"Expected low risk for retail merchant, got {pred.risk_score}"


def test_benign_merchant_with_supplier_payout_has_low_risk(trained_risk_model: MuleRiskModel) -> None:
    """Verifies that a merchant making legitimate delayed supplier payouts retains low risk."""
    t0 = datetime(2026, 10, 8, 8, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    # 8 retail customer purchases over 8 hours
    for i in range(8):
        g.add_event(_make_event(f"sale-{i}", f"customer-{i}", "superstore", 100_000, t0 + timedelta(hours=i)))

    # Legitimate supplier payout 6 hours after last sale (total delay > 6 hours, no rapid pass-through)
    g.add_event(_make_event("payout-1", "superstore", "wholesaler", 300_000, t0 + timedelta(hours=14)))

    pred = trained_risk_model.predict_risk(
        graph=g,
        account_id="superstore",
        as_of_time=t0 + timedelta(hours=16),
    )
    assert pred.risk_score < 0.35, f"Expected low risk for merchant with delayed payout, got {pred.risk_score}"


def test_high_velocity_mule_has_high_risk(trained_risk_model: MuleRiskModel) -> None:
    """Verifies that an account with rapid pass-through (<2 min) and high forwarding ratio is flagged."""
    t0 = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    g = TemporalGraph()
    # ₹5,00,000 in minor units (paise)
    g.add_event(_make_event("in-1", "victim-account", "mule-account", 50_000_000, t0))
    # Forwarded 98% within 90 seconds
    g.add_event(_make_event("out-1", "mule-account", "cashout-account", 49_000_000, t0 + timedelta(seconds=90)))

    pred = trained_risk_model.predict_risk(
        graph=g,
        account_id="mule-account",
        as_of_time=t0 + timedelta(minutes=5),
    )
    assert pred.risk_score >= 0.70, f"Expected high risk for rapid mule, got {pred.risk_score}"
