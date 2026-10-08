"""
AEGIS-Flow ML Intelligence Layer — Mule Risk Classifier
=======================================================

Supervised tree-based model (LightGBM) for account-level mule and
laundering risk classification.

Key Design Principles:
----------------------
1. Evidence, Not Adjudication:
   Produces calibrated risk scores in [0, 1] and explainable evidence signals.
   Does NOT make legal determinations, freeze accounts, or block payments.
2. Cold-Start Resilient:
   Operates whether an account is history-rich or cold-start (zero pre-case history).
   Outputs explicit `EvidenceMaturity` and penalizes confidence when evidence is sparse.
3. Deterministic & Reproducible:
   Pinned random seeds (seed=42), reproducible preprocessing, and strict feature ordering.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Sequence

import joblib
import lightgbm as lgb
import numpy as np
from sklearn.calibration import CalibratedClassifierCV

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.ml.features import (
    ACCOUNT_FEATURE_NAMES,
    determine_evidence_maturity,
    extract_account_features,
)
from backend.app.ml.schemas import (
    AccountRiskPrediction,
    EvidenceMaturity,
    FEATURE_SCHEMA_VERSION,
    FeatureImportanceSignal,
    MODEL_VERSION,
)


class MuleRiskModel:
    """Supervised risk model for account-level mule classification."""

    def __init__(
        self,
        random_state: int = 42,
        model_version: str = MODEL_VERSION,
        feature_version: str = FEATURE_SCHEMA_VERSION,
    ) -> None:
        self.random_state = random_state
        self.model_version = model_version
        self.feature_version = feature_version
        self.feature_names = list(ACCOUNT_FEATURE_NAMES)

        # Base estimator: compact LightGBM tree ensemble
        self._base_model = lgb.LGBMClassifier(
            objective="binary",
            n_estimators=45,
            learning_rate=0.08,
            num_leaves=15,
            max_depth=4,
            min_child_samples=5,
            subsample=0.85,
            colsample_bytree=0.85,
            random_state=self.random_state,
            n_jobs=1,
            verbose=-1,
        )
        self._calibrated_model: CalibratedClassifierCV | None = None
        self._is_fitted: bool = False

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sample_weight: np.ndarray | None = None,
    ) -> MuleRiskModel:
        """Fit the LightGBM classifier with probability calibration.

        Uses sigmoid calibration to ensure probabilities reflect empirical risk.
        """
        if len(X) == 0:
            raise ValueError("Training matrix X cannot be empty.")
        if len(np.unique(y)) < 2:
            raise ValueError("Training targets y must contain at least two classes.")

        # Train base LightGBM model
        self._base_model.fit(X, y, sample_weight=sample_weight)

        # Fit probability calibrator using cross-validation over the base estimator
        self._calibrated_model = CalibratedClassifierCV(
            estimator=self._base_model,
            method="sigmoid",
            cv=3,
        )
        self._calibrated_model.fit(X, y, sample_weight=sample_weight)
        self._is_fitted = True
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict calibrated posterior probability distribution [P(neg), P(pos)]."""
        if not self._is_fitted:
            raise RuntimeError("MuleRiskModel must be fitted before predict_proba.")
        if self._calibrated_model is not None:
            return self._calibrated_model.predict_proba(X)
        return self._base_model.predict_proba(X)

    def predict_risk_score(self, features: dict[str, float]) -> float:
        """Return the scalar probability of mule risk in [0.0, 1.0]."""
        row = np.array([[features[name] for name in self.feature_names]], dtype=np.float32)
        proba = self.predict_proba(row)
        score = float(proba[0, 1])
        return max(0.0, min(1.0, score))

    def compute_confidence(
        self,
        risk_score: float,
        evidence_maturity: EvidenceMaturity,
        total_tx_count: int,
    ) -> float:
        """Derive confidence score in [0.0, 1.0] reflecting signal clarity and evidence maturity.

        Accounts with limited evidence have capped confidence to prevent false certainty.
        """
        # Distance from undecided boundary 0.5: margin in [0, 1]
        distance_from_boundary = abs(risk_score - 0.5) * 2.0

        if evidence_maturity == EvidenceMaturity.LIMITED_EVIDENCE:
            # When observations are very few (e.g. <=1 tx), maximum confidence is strictly capped
            base_conf = 0.35 + 0.20 * distance_from_boundary
            return round(min(0.55, base_conf), 4)

        if evidence_maturity == EvidenceMaturity.FLOW_DOMINANT:
            # Flow is active; confidence scales with flow volume and score certainty
            volume_factor = min(1.0, float(total_tx_count) / 4.0)
            base_conf = 0.50 + 0.40 * distance_from_boundary * volume_factor
            return round(min(0.90, max(0.40, base_conf)), 4)

        # STRONG_HISTORY: high telemetry
        base_conf = 0.60 + 0.38 * distance_from_boundary
        return round(min(0.98, max(0.50, base_conf)), 4)

    def explain(
        self,
        features: dict[str, float],
        risk_score: float,
    ) -> tuple[list[str], list[FeatureImportanceSignal]]:
        """Generate human-interpretable evidence summaries and structured signals."""
        summaries: list[str] = []
        signals: list[FeatureImportanceSignal] = []

        forwarding_ratio = features.get("forwarding_ratio", 0.0)
        has_rapid_pass = bool(features.get("has_rapid_pass_through", 0.0))
        min_pass_sec = features.get("min_pass_through_seconds", 86400.0)
        in_degree = int(features.get("in_degree", 0.0))
        out_degree = int(features.get("out_degree", 0.0))
        total_degree = int(features.get("total_degree", 0.0))
        fan_in_ratio = features.get("fan_in_ratio", 0.0)
        fan_out_ratio = features.get("fan_out_ratio", 0.0)
        is_cold = bool(features.get("is_cold_start", 0.0))
        hist_count = int(features.get("historical_tx_count", 0.0))
        burst_ratio = features.get("burst_ratio_1h", 0.0)

        # 1. Forwarding ratio
        if forwarding_ratio >= 0.85:
            desc = f"High forwarding ratio ({forwarding_ratio * 100:.1f}%): nearly all incoming capital quickly dispatched."
            summaries.append(desc)
            signals.append(
                FeatureImportanceSignal(
                    feature_name="forwarding_ratio",
                    value=forwarding_ratio,
                    contribution_score=0.35,
                    description=desc,
                )
            )
        elif forwarding_ratio < 0.15 and in_degree > 3:
            desc = f"Low forwarding ratio ({forwarding_ratio * 100:.1f}%): capital is retained or aggregated (merchant/sink signature)."
            summaries.append(desc)
            signals.append(
                FeatureImportanceSignal(
                    feature_name="forwarding_ratio",
                    value=forwarding_ratio,
                    contribution_score=-0.25,
                    description=desc,
                )
            )

        # 2. Rapid pass-through
        if has_rapid_pass and min_pass_sec < 300.0:
            desc = f"Rapid pass-through observed: inter-hop latency of {min_pass_sec:.0f}s (<5 minutes)."
            summaries.append(desc)
            signals.append(
                FeatureImportanceSignal(
                    feature_name="min_pass_through_seconds",
                    value=min_pass_sec,
                    contribution_score=0.30,
                    description=desc,
                )
            )

        # 3. Fan-in or Fan-out motifs
        if in_degree >= 3 and fan_in_ratio > 0.65:
            desc = f"Fan-in pattern: {in_degree} distinct incoming flows converging on account."
            summaries.append(desc)
            signals.append(
                FeatureImportanceSignal(
                    feature_name="fan_in_ratio",
                    value=fan_in_ratio,
                    contribution_score=0.20,
                    description=desc,
                )
            )
        if out_degree >= 3 and fan_out_ratio > 0.65:
            desc = f"Fan-out dispersion: {out_degree} distinct downstream recipients."
            summaries.append(desc)
            signals.append(
                FeatureImportanceSignal(
                    feature_name="fan_out_ratio",
                    value=fan_out_ratio,
                    contribution_score=0.20,
                    description=desc,
                )
            )

        # 4. Cold-start vs History
        if is_cold:
            desc = "Cold-start entity: zero pre-incident history observed."
            summaries.append(desc)
            signals.append(
                FeatureImportanceSignal(
                    feature_name="is_cold_start",
                    value=1.0,
                    contribution_score=0.15,
                    description=desc,
                )
            )
        elif hist_count >= 5:
            desc = f"Established historical profile: {hist_count} verified pre-incident transactions."
            summaries.append(desc)
            signals.append(
                FeatureImportanceSignal(
                    feature_name="historical_tx_count",
                    value=float(hist_count),
                    contribution_score=-0.15,
                    description=desc,
                )
            )

        # 5. Burstiness
        if burst_ratio > 0.8 and total_degree >= 3:
            desc = f"High burst concentration: {burst_ratio * 100:.1f}% of all activity occurred in the past 1 hour."
            summaries.append(desc)
            signals.append(
                FeatureImportanceSignal(
                    feature_name="burst_ratio_1h",
                    value=burst_ratio,
                    contribution_score=0.15,
                    description=desc,
                )
            )

        # Default fallback summary if no specific condition triggered
        if not summaries:
            if risk_score > 0.5:
                summaries.append(f"Moderate anomalous activity indicated across graph topology (risk {risk_score:.2f}).")
            else:
                summaries.append("Behavior consistent with standard baseline transaction flow.")

        return summaries, signals

    def predict_risk(
        self,
        graph: TemporalGraph,
        account_id: str,
        as_of_time: datetime,
        history_cutoff_time: datetime | None = None,
        institution_map: dict[str, str] | None = None,
    ) -> AccountRiskPrediction:
        """Produce an end-to-end AccountRiskPrediction for an account at as_of_time."""
        features = extract_account_features(
            graph=graph,
            account_id=account_id,
            as_of_time=as_of_time,
            history_cutoff_time=history_cutoff_time,
            institution_map=institution_map,
        )

        total_tx = int(features["total_degree"])
        hist_tx = int(features["historical_tx_count"])
        has_hist = bool(features["has_historical_profile"])
        is_cold = bool(features["is_cold_start"])

        maturity = determine_evidence_maturity(
            total_tx_count=total_tx,
            historical_tx_count=hist_tx,
            has_historical_profile=has_hist,
        )

        score = self.predict_risk_score(features)
        confidence = self.compute_confidence(
            risk_score=score,
            evidence_maturity=maturity,
            total_tx_count=total_tx,
        )
        evidence_summary, top_signals = self.explain(features, score)

        return AccountRiskPrediction(
            account_id=account_id,
            risk_score=round(score, 4),
            confidence=confidence,
            evidence_maturity=maturity,
            is_cold_start=is_cold,
            model_version=self.model_version,
            feature_version=self.feature_version,
            prediction_timestamp=as_of_time,
            evidence_summary=evidence_summary,
            top_signals=top_signals,
        )

    def save(self, filepath: str | Path) -> None:
        """Persist model artefacts and metadata."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        bundle = {
            "model_version": self.model_version,
            "feature_version": self.feature_version,
            "feature_names": self.feature_names,
            "random_state": self.random_state,
            "base_model": self._base_model,
            "calibrated_model": self._calibrated_model,
            "is_fitted": self._is_fitted,
        }
        joblib.dump(bundle, path)

    @classmethod
    def load(cls, filepath: str | Path) -> MuleRiskModel:
        """Load persisted model artefacts."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Model artefact not found at {path}")
        bundle = joblib.load(path)
        instance = cls(
            random_state=bundle.get("random_state", 42),
            model_version=bundle.get("model_version", MODEL_VERSION),
            feature_version=bundle.get("feature_version", FEATURE_SCHEMA_VERSION),
        )
        instance.feature_names = bundle["feature_names"]
        instance._base_model = bundle["base_model"]
        instance._calibrated_model = bundle.get("calibrated_model")
        instance._is_fitted = bundle.get("is_fitted", True)
        return instance
