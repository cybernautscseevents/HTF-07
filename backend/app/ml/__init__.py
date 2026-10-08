"""
AEGIS-Flow ML Intelligence Layer
================================

Predictive intelligence layer positioned above the deterministic temporal graph.

Provides:
- Mule / Account-level risk classification
- Cold-start handling & evidence maturity assessment
- Next-hop destination ranking
- Structured evidence envelope generation
"""

from backend.app.ml.features import (
    ACCOUNT_FEATURE_NAMES,
    NEXT_HOP_FEATURE_NAMES,
    extract_account_features,
    extract_next_hop_candidate_features,
)
from backend.app.ml.next_hop import NextHopPredictor
from backend.app.ml.risk_model import MuleRiskModel
from backend.app.ml.schemas import (
    AccountRiskPrediction,
    ColdStartComparisonMetrics,
    EvidenceMaturity,
    FeatureImportanceSignal,
    NegativeControlMetrics,
    NextHopCandidate,
    NextHopEvaluationMetrics,
    NextHopPrediction,
    RiskEvaluationMetrics,
)

__all__ = [
    "ACCOUNT_FEATURE_NAMES",
    "NEXT_HOP_FEATURE_NAMES",
    "AccountRiskPrediction",
    "ColdStartComparisonMetrics",
    "EvidenceMaturity",
    "FeatureImportanceSignal",
    "MuleRiskModel",
    "NegativeControlMetrics",
    "NextHopCandidate",
    "NextHopEvaluationMetrics",
    "NextHopPrediction",
    "NextHopPredictor",
    "RiskEvaluationMetrics",
    "extract_account_features",
    "extract_next_hop_candidate_features",
]
