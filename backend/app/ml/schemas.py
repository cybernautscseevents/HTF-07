"""
AEGIS-Flow ML Intelligence Layer — Schemas
==========================================

Machine-readable schemas for feature vectors, risk classification,
cold-start signals, next-hop ranking, and evaluation outputs.

These schemas sit ABOVE the deterministic temporal graph and package
predictions into structured intelligence envelopes without making
legal or account-freezing decisions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum, unique
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from contracts.enums import EvidenceProviderType
from contracts.evidence import EvidenceEnvelope

FEATURE_SCHEMA_VERSION = "1.0.0"
MODEL_VERSION = "aegis-flow-ml-v1"


@unique
class EvidenceMaturity(StrEnum):
    """Maturity level of historical and contextual evidence available for an account."""

    STRONG_HISTORY = "strong_history"
    """Substantial historical profile observed prior to current incident window."""

    FLOW_DOMINANT = "flow_dominant"
    """Account activity is primarily or exclusively within the current incident flow."""

    LIMITED_EVIDENCE = "limited_evidence"
    """Sparse or newly created account with very few observed transactions overall."""


class FeatureImportanceSignal(BaseModel):
    """Key feature attribution explaining a model score."""

    model_config = ConfigDict(strict=True, frozen=True)

    feature_name: str = Field(..., description="Canonical name of the extracted feature.")
    value: float = Field(..., description="Observed numeric value of the feature.")
    contribution_score: float | None = Field(
        default=None,
        description="Relative contribution or tree split importance of this feature.",
    )
    description: str = Field(..., description="Human-interpretable explanation of the signal.")


class AccountRiskPrediction(BaseModel):
    """Structured risk prediction for a single account.

    Carries evidence signals and calibrated risk score. Does NOT make
    operational block/freeze decisions.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    account_id: str = Field(..., min_length=1, description="Opaque account identifier.")
    risk_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Calibrated probability in [0, 1] of mule/laundering participation.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in [0, 1] based on evidence maturity and calibration.",
    )
    evidence_maturity: EvidenceMaturity = Field(
        ...,
        description="Whether evidence is based on strong history or primarily current flow.",
    )
    is_cold_start: bool = Field(
        ...,
        description="True if account lacks pre-incident historical activity.",
    )
    model_version: str = Field(default=MODEL_VERSION, description="Model identifier and release version.")
    feature_version: str = Field(default=FEATURE_SCHEMA_VERSION, description="Feature pipeline schema version.")
    prediction_timestamp: datetime = Field(
        ...,
        description="Timezone-aware timestamp when prediction was computed.",
    )
    evidence_summary: list[str] = Field(
        default_factory=list,
        description="List of plain-language driver statements explaining the prediction.",
    )
    top_signals: list[FeatureImportanceSignal] = Field(
        default_factory=list,
        description="Structured key signals driving the prediction.",
    )

    @field_validator("prediction_timestamp")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware.")
        return v

    def to_evidence_envelope(self, case_id: str) -> EvidenceEnvelope:
        """Package this prediction into a canonical EvidenceEnvelope."""
        return EvidenceEnvelope(
            evidence_id=f"evi-ml-risk-{self.account_id}-{uuid.uuid4().hex[:8]}",
            case_id=case_id,
            provider_type=EvidenceProviderType.ML_MODEL,
            provider_name=f"aegis-flow-risk-{self.model_version}",
            summary=(
                f"Mule risk score {self.risk_score:.3f} (confidence: {self.confidence:.2f}, "
                f"maturity: {self.evidence_maturity.value}) for account {self.account_id}"
            ),
            body=self.model_dump(mode="json"),
            created_at=self.prediction_timestamp,
        )


class NextHopCandidate(BaseModel):
    """Ranked candidate destination account for downstream flow."""

    model_config = ConfigDict(strict=True, frozen=True)

    account_id: str = Field(..., min_length=1, description="Candidate recipient account ID.")
    predicted_probability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Estimated probability that funds transfer next to this account.",
    )
    rank: int = Field(..., ge=1, description="1-based ranking among all candidates.")
    candidate_signals: dict[str, float] = Field(
        default_factory=dict,
        description="Candidate-level features (e.g. shared counterparties, volume capacity).",
    )


class NextHopPrediction(BaseModel):
    """Next-hop destination predictions for a given source account."""

    model_config = ConfigDict(strict=True, frozen=True)

    source_account_id: str = Field(..., min_length=1, description="Account from which funds are moving.")
    candidates: list[NextHopCandidate] = Field(
        default_factory=list,
        description="Ranked candidate accounts sorted by descending probability.",
    )
    model_version: str = Field(default=MODEL_VERSION, description="Model identifier.")
    prediction_timestamp: datetime = Field(
        ...,
        description="Timezone-aware timestamp when prediction was computed.",
    )
    top_1_account_id: str | None = Field(
        default=None,
        description="Most probable next destination account ID.",
    )

    @field_validator("prediction_timestamp")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware.")
        return v

    def to_evidence_envelope(self, case_id: str) -> EvidenceEnvelope:
        """Package next-hop prediction into a canonical EvidenceEnvelope."""
        top_dest = self.top_1_account_id or "none"
        return EvidenceEnvelope(
            evidence_id=f"evi-ml-nexthop-{self.source_account_id}-{uuid.uuid4().hex[:8]}",
            case_id=case_id,
            provider_type=EvidenceProviderType.ML_MODEL,
            provider_name=f"aegis-flow-nexthop-{self.model_version}",
            summary=(
                f"Next-hop prediction for {self.source_account_id}: "
                f"top destination {top_dest} ({len(self.candidates)} candidates evaluated)"
            ),
            body=self.model_dump(mode="json"),
            created_at=self.prediction_timestamp,
        )


class RiskEvaluationMetrics(BaseModel):
    """Empirical evaluation metrics for the account risk classifier."""

    model_config = ConfigDict(strict=True, frozen=True)

    precision: float | None = Field(default=None, ge=0.0, le=1.0)
    recall: float | None = Field(default=None, ge=0.0, le=1.0)
    f1: float | None = Field(default=None, ge=0.0, le=1.0)
    roc_auc: float | None = Field(default=None, ge=0.0, le=1.0)
    pr_auc: float | None = Field(default=None, ge=0.0, le=1.0)
    brier_score: float = Field(..., ge=0.0, le=1.0)
    confusion_matrix: dict[str, int] = Field(..., description="Dict with keys 'tp', 'fp', 'tn', 'fn'.")
    sample_count: int = Field(..., ge=0)
    positive_count: int = Field(default=0, ge=0)
    negative_count: int = Field(default=0, ge=0)


class ColdStartComparisonMetrics(BaseModel):
    """Comparative performance between history-rich and cold-start cohorts and masking stress test."""

    model_config = ConfigDict(strict=True, frozen=True)

    unmasked_metrics: RiskEvaluationMetrics
    masked_metrics: RiskEvaluationMetrics
    masking_degradation_f1: float = Field(
        ...,
        description="F1 drop when all historical features are masked to zero: unmasked.f1 - masked.f1.",
    )
    cohort_history_rich: RiskEvaluationMetrics | None = None
    cohort_cold_start: RiskEvaluationMetrics | None = None
    cohort_degradation_f1: float | None = Field(
        default=None,
        description="Cohort F1 difference: history_rich.f1 - cold_start.f1 (None if positive examples absent).",
    )


class NextHopEvaluationMetrics(BaseModel):
    """Empirical evaluation metrics for the next-hop predictor."""

    model_config = ConfigDict(strict=True, frozen=True)

    top_1_accuracy: float = Field(..., ge=0.0, le=1.0)
    top_3_accuracy: float = Field(..., ge=0.0, le=1.0)
    mean_reciprocal_rank: float = Field(..., ge=0.0, le=1.0)
    sample_count: int = Field(..., ge=0)


class NegativeControlMetrics(BaseModel):
    """Evaluation on benign control scenarios (e.g. retail merchant)."""

    model_config = ConfigDict(strict=True, frozen=True)

    scenario_type: str = Field(...)
    total_accounts: int = Field(..., ge=0)
    flagged_accounts: int = Field(..., ge=0)
    false_positive_rate: float = Field(..., ge=0.0, le=1.0)
    merchant_risk_score: float = Field(..., ge=0.0, le=1.0)
    merchant_account_id: str = Field(...)
