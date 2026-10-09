"""
AEGIS-Flow ML Intelligence Layer — Next-Hop Predictor
=====================================================

Predicts the most probable next-hop account destinations for funds moving
from a given source account based on temporal graph state up to prediction time.

Guarantees:
-----------
1. Strict Temporal Semantics:
   Evaluates only candidates and interactions occurring <= as_of_time.
2. Normalized Probabilities:
   Candidate scores are normalized via softmax over the candidate pool.
3. Top-k Ranking & Explainability:
   Outputs candidate rank, probability, and key candidate signals.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import joblib
import lightgbm as lgb
import numpy as np

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.ml.features import (
    NEXT_HOP_FEATURE_NAMES,
    extract_next_hop_candidate_features,
)
from backend.app.ml.schemas import (
    MODEL_VERSION,
    NextHopCandidate,
    NextHopPrediction,
)


def _softmax(x: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    """Numerically stable softmax."""
    scaled = x / max(0.01, temperature)
    e_x = np.exp(scaled - np.max(scaled))
    return e_x / np.sum(e_x)


def get_upstream_ancestors(
    graph: TemporalGraph, account_id: str, as_of_time: datetime
) -> set[str]:
    """Find all prior accounts that sent funds flowing into account_id up to as_of_time."""
    ancestors: set[str] = set()
    queue = [account_id]
    visited = {account_id}
    while queue:
        curr = queue.pop(0)
        for edge in graph.incoming(curr, end=as_of_time, active_only=True):
            sender = edge.sender_id
            if sender not in visited:
                visited.add(sender)
                ancestors.add(sender)
                queue.append(sender)
    return ancestors


class NextHopPredictor:
    """Predicts next-hop account destinations given graph state."""

    def __init__(
        self,
        random_state: int = 42,
        model_version: str = MODEL_VERSION,
    ) -> None:
        self.random_state = random_state
        self.model_version = model_version
        self.feature_names = list(NEXT_HOP_FEATURE_NAMES)

        # Tree ensemble for candidate affinity scoring
        self._model = lgb.LGBMClassifier(
            objective="binary",
            n_estimators=35,
            learning_rate=0.08,
            num_leaves=15,
            max_depth=4,
            min_child_samples=5,
            random_state=self.random_state,
            n_jobs=1,
            verbose=-1,
        )
        self._is_fitted: bool = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> NextHopPredictor:
        """Fit candidate affinity scoring model on pairwise features."""
        if len(X) == 0:
            raise ValueError("Training matrix X cannot be empty.")
        if len(np.unique(y)) < 2:
            raise ValueError("Training targets y must contain at least two classes.")

        self._model.fit(X, y)
        self._is_fitted = True
        return self

    def predict_next_hop(
        self,
        graph: TemporalGraph,
        source_account_id: str,
        as_of_time: datetime,
        candidate_pool: Sequence[str] | None = None,
        institution_map: dict[str, str] | None = None,
        top_k: int = 5,
    ) -> NextHopPrediction:
        """Predict and rank likely next destination accounts from source_account_id.

        Parameters
        ----------
        graph : TemporalGraph
            The temporal graph up to as_of_time.
        source_account_id : str
            The source account where funds currently reside.
        as_of_time : datetime
            Strict temporal boundary. No event after this time is examined.
        candidate_pool : Sequence[str], optional
            Pool of candidate destination account IDs. If None, all distinct
            accounts observed in graph <= as_of_time (except source) are evaluated.
        institution_map : dict[str, str], optional
            Optional account-to-institution mapping.
        top_k : int
            Number of top candidates to return.
        """
        if as_of_time.tzinfo is None:
            raise ValueError("as_of_time must be timezone-aware.")

        # Determine eligible candidate accounts
        if candidate_pool is not None:
            candidates = [c for c in candidate_pool if c != source_account_id]
        else:
            # Active accounts observed in the graph up to as_of_time
            edges_up_to = graph.events_between(end=as_of_time, active_only=True)
            active_nodes = {e.sender_id for e in edges_up_to} | {e.receiver_id for e in edges_up_to}
            # Exclude upstream ancestors in the observed flow leading into source_account_id
            # to strictly prevent reversing observed flow direction or revisiting prior accounts.
            upstream_ancestors = get_upstream_ancestors(graph, source_account_id, as_of_time)
            candidates = [
                c for c in active_nodes
                if c != source_account_id and c not in upstream_ancestors
            ]

        if not candidates:
            return NextHopPrediction(
                source_account_id=source_account_id,
                candidates=[],
                model_version=self.model_version,
                prediction_timestamp=as_of_time,
                top_1_account_id=None,
            )

        # Extract features for each candidate
        feature_dicts: list[dict[str, float]] = []
        feature_rows: list[list[float]] = []

        for cand_id in candidates:
            f = extract_next_hop_candidate_features(
                graph=graph,
                source_id=source_account_id,
                candidate_id=cand_id,
                as_of_time=as_of_time,
                institution_map=institution_map,
            )
            feature_dicts.append(f)
            feature_rows.append([f[name] for name in self.feature_names])

        X = np.array(feature_rows, dtype=np.float32)

        # Predict raw scores
        if self._is_fitted:
            # Probability of affinity from binary classifier
            probas = self._model.predict_proba(X)[:, 1]
            # Softmax to form probability distribution over the candidate pool
            norm_probas = _softmax(probas, temperature=0.5)
        else:
            # Heuristic baseline if not yet fitted: score by shared counterparties and capacity
            raw_scores = []
            for fd in feature_dicts:
                # Evidence requires a plausible relational link:
                # past outbound transfers, shared counterparties, or shared institution.
                relational_evidence = (
                    fd["past_transfers_count"] * 2.0
                    + fd["shared_counterparties_count"] * 1.5
                    + fd["same_institution"] * 0.5
                )
                if relational_evidence > 0.0:
                    score = relational_evidence + fd["candidate_in_degree"] * 0.5
                else:
                    score = 0.0
                raw_scores.append(score)

            valid_cand_indices = [i for i, s in enumerate(raw_scores) if s > 0.0]
            if not valid_cand_indices:
                return NextHopPrediction(
                    source_account_id=source_account_id,
                    candidates=[],
                    model_version=self.model_version,
                    prediction_timestamp=as_of_time,
                    top_1_account_id=None,
                )

            candidates = [candidates[i] for i in valid_cand_indices]
            feature_dicts = [feature_dicts[i] for i in valid_cand_indices]
            filtered_scores = np.array([raw_scores[i] for i in valid_cand_indices], dtype=np.float32)
            norm_probas = _softmax(filtered_scores, temperature=1.0)

        # Rank candidates descending by probability
        ranked_indices = np.argsort(-norm_probas)

        candidate_results: list[NextHopCandidate] = []
        for rank_idx, idx in enumerate(ranked_indices[:top_k], start=1):
            cand_id = candidates[idx]
            cand_prob = float(norm_probas[idx])
            signals = {
                "shared_counterparties": feature_dicts[idx]["shared_counterparties_count"],
                "candidate_in_degree": feature_dicts[idx]["candidate_in_degree"],
                "candidate_forwarding_ratio": feature_dicts[idx]["candidate_forwarding_ratio"],
                "past_transfers_count": feature_dicts[idx]["past_transfers_count"],
            }
            candidate_results.append(
                NextHopCandidate(
                    account_id=cand_id,
                    predicted_probability=round(cand_prob, 4),
                    rank=rank_idx,
                    candidate_signals=signals,
                )
            )

        top_1 = candidate_results[0].account_id if candidate_results else None

        return NextHopPrediction(
            source_account_id=source_account_id,
            candidates=candidate_results,
            model_version=self.model_version,
            prediction_timestamp=as_of_time,
            top_1_account_id=top_1,
        )

    def save(self, filepath: str | Path) -> None:
        """Persist next-hop predictor model."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        bundle = {
            "model_version": self.model_version,
            "feature_names": self.feature_names,
            "random_state": self.random_state,
            "model": self._model,
            "is_fitted": self._is_fitted,
        }
        joblib.dump(bundle, path)

    @classmethod
    def load(cls, filepath: str | Path) -> NextHopPredictor:
        """Load persisted next-hop predictor."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Model artefact not found at {path}")
        bundle = joblib.load(path)
        instance = cls(
            random_state=bundle.get("random_state", 42),
            model_version=bundle.get("model_version", MODEL_VERSION),
        )
        instance.feature_names = bundle["feature_names"]
        instance._model = bundle["model"]
        instance._is_fitted = bundle.get("is_fitted", True)
        return instance
