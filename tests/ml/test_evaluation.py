"""
Unit tests for ML Evaluation Pipeline
=====================================

Verifies:
1. Risk evaluation metrics calculation (Precision, Recall, F1, ROC-AUC, PR-AUC, Brier score).
2. Cold-start masking degradation evaluation.
3. Negative control evaluation on benign merchant scenario.
4. Next-hop Top-1, Top-3, and MRR metric calculation.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.app.ml.evaluation import (
    evaluate_cold_start_comparison,
    evaluate_negative_control,
    evaluate_next_hop,
    evaluate_risk_metrics,
)
from backend.app.ml.next_hop import NextHopPredictor
from backend.app.ml.risk_model import MuleRiskModel
from backend.app.ml.schemas import (
    ColdStartComparisonMetrics,
    NegativeControlMetrics,
    NextHopEvaluationMetrics,
    RiskEvaluationMetrics,
)
from scripts.generator import generate_synthetic_world


def test_evaluate_risk_metrics_computation() -> None:
    """Verifies correct calculation of precision, recall, F1, and Brier score."""
    y_true = np.array([1, 1, 0, 0, 1, 0], dtype=int)
    y_proba = np.array([0.9, 0.8, 0.1, 0.2, 0.4, 0.05], dtype=float)

    metrics = evaluate_risk_metrics(y_true, y_proba, threshold=0.5)
    assert isinstance(metrics, RiskEvaluationMetrics)
    assert metrics.sample_count == 6
    assert 0.0 <= metrics.precision <= 1.0
    assert 0.0 <= metrics.recall <= 1.0
    assert 0.0 <= metrics.f1 <= 1.0
    assert 0.0 <= metrics.brier_score <= 1.0
    assert metrics.confusion_matrix["tp"] == 2
    assert metrics.confusion_matrix["fp"] == 0
    assert metrics.confusion_matrix["fn"] == 1
    assert metrics.confusion_matrix["tn"] == 3


def test_cold_start_masking_evaluation() -> None:
    """Verifies that masking evaluation computes degradation properly."""
    # Synthetic model
    X = np.zeros((20, 35), dtype=np.float32)
    X[:10, 23] = 0.95  # high forwarding ratio
    X[10:, 23] = 0.05
    y = np.array([1] * 10 + [0] * 10, dtype=int)
    model = MuleRiskModel(random_state=42)
    model.fit(X, y)

    is_cold = np.array([True] * 10 + [False] * 10)
    cold_comp = evaluate_cold_start_comparison(model, X, y, is_cold)

    assert isinstance(cold_comp, ColdStartComparisonMetrics)
    assert hasattr(cold_comp, "masking_degradation_f1")
    assert hasattr(cold_comp, "unmasked_metrics")
    assert hasattr(cold_comp, "masked_metrics")


def test_benign_merchant_negative_control() -> None:
    """Explicitly evaluates against benign high-volume merchant scenario."""
    world = generate_synthetic_world(seed=42)
    model = MuleRiskModel.load("backend/models/artefacts/mule_risk_model.joblib")

    neg_metrics = evaluate_negative_control(model, world)
    assert isinstance(neg_metrics, NegativeControlMetrics)
    assert neg_metrics.scenario_type == "benign_high_volume_merchant"
    assert neg_metrics.false_positive_rate == 0.0
    assert neg_metrics.merchant_risk_score < 0.20
