"""
AEGIS-Flow ML Intelligence Layer — Evaluation Pipeline
======================================================

Comprehensive evaluation pipeline for:
1. Mule / Account Risk Classification (Precision, Recall, F1, ROC-AUC, PR-AUC, Brier score, Confusion Matrix)
2. Cold-Start Performance vs. History-Rich Cohorts (Performance Degradation Analysis)
3. Next-Hop Destination Prediction (Top-1, Top-3, MRR)
4. Negative Control Evaluation (Benign High-Volume Merchant Zero False Positive Check)

No metrics are fabricated or estimated; all are computed from concrete empirical runs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.ml.features import (
    ACCOUNT_FEATURE_NAMES,
    NEXT_HOP_FEATURE_NAMES,
    extract_account_features,
    extract_next_hop_candidate_features,
)
from backend.app.ml.next_hop import NextHopPredictor
from backend.app.ml.risk_model import MuleRiskModel
from backend.app.ml.schemas import (
    ColdStartComparisonMetrics,
    NegativeControlMetrics,
    NextHopEvaluationMetrics,
    RiskEvaluationMetrics,
)
from scripts.generator import SyntheticWorld


# ── Dataset Builders ─────────────────────────────────────────────────────────


def create_risk_dataset_from_worlds(
    worlds: Sequence[SyntheticWorld],
    observation_mode: str = "case_opened",
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]], np.ndarray]:
    """Extract (X, y, metadata, is_cold_mask) for account risk training and evaluation.

    Causal Intervention Structure:
    Features for each evaluated account are extracted strictly using events with occurred_at <= t,
    where t is the observation / fraud-seed timestamp for the incident.
    Transactions occurring after t are strictly in the future and excluded from feature computation.
    Future mule behavior is used exclusively as the ground-truth evaluation label (y).
    """
    feature_rows: list[list[float]] = []
    labels: list[int] = []
    metadata: list[dict[str, Any]] = []
    is_cold_flags: list[bool] = []

    for world in worlds:
        graph = TemporalGraph()
        graph.build_case(world.transactions)

        inst_map = {a.account_id: a.institution for a in world.accounts if a.institution}

        # Ground-truth labels ONLY from truths
        fraud_account_set = set()
        for truth in world.truths:
            fraud_account_set.update(truth.fraud_accounts)

        # Map scenario to observation / fraud-seed timestamp t
        case_opened_map = {c.case_id: c.opened_at for c in world.cases}
        scenario_obs_time: dict[str, datetime] = {}
        for truth in world.truths:
            if truth.case_id and truth.case_id in case_opened_map:
                if observation_mode == "fraud_seed":
                    seed_txs = [tx for tx in world.transactions if tx.transaction_id in truth.seed_transaction_ids]
                    scenario_obs_time[truth.scenario_id] = min(tx.occurred_at for tx in seed_txs) if seed_txs else case_opened_map[truth.case_id]
                else:
                    scenario_obs_time[truth.scenario_id] = case_opened_map[truth.case_id]
            else:
                # Benign control scenario: observation cutoff after retail customer activity
                sc_txs = [
                    tx for tx in world.transactions
                    if tx.sender.account_id.startswith(truth.scenario_id) or tx.receiver.account_id.startswith(truth.scenario_id)
                ]
                if sc_txs:
                    min_t = min(tx.occurred_at for tx in sc_txs)
                    max_t = max(tx.occurred_at for tx in sc_txs)
                    scenario_obs_time[truth.scenario_id] = min_t + (max_t - min_t) * 0.85
                else:
                    scenario_obs_time[truth.scenario_id] = max(tx.occurred_at for tx in world.transactions)

        for acc in world.accounts:
            prefix = acc.account_id.split("-acc-")[0]
            obs_t = scenario_obs_time.get(prefix)
            if not obs_t:
                continue

            # Check if account has any observed active edges up to observation time t
            inc = graph.incoming(acc.account_id, end=obs_t, active_only=True)
            out = graph.outgoing(acc.account_id, end=obs_t, active_only=True)
            if not inc and not out:
                continue

            feats = extract_account_features(
                graph=graph,
                account_id=acc.account_id,
                as_of_time=obs_t,
                history_cutoff_time=None,
                institution_map=inst_map,
            )

            is_fraud = 1 if acc.account_id in fraud_account_set else 0
            is_cold = bool(feats["is_cold_start"])

            feature_rows.append([feats[name] for name in ACCOUNT_FEATURE_NAMES])
            labels.append(is_fraud)
            is_cold_flags.append(is_cold)
            metadata.append({
                "account_id": acc.account_id,
                "role": acc.label,
                "is_fraud": is_fraud,
                "is_cold": is_cold,
                "observation_time": obs_t.isoformat(),
            })

    X = np.array(feature_rows, dtype=np.float32)
    y = np.array(labels, dtype=np.int32)
    is_cold_mask = np.array(is_cold_flags, dtype=bool)
    return X, y, metadata, is_cold_mask


def create_next_hop_dataset_from_worlds(
    worlds: Sequence[SyntheticWorld],
) -> tuple[np.ndarray, np.ndarray]:
    """Extract pairwise candidate training samples (X_pairs, y_pairs) from synthetic worlds.

    Strict Temporal Causality:
    Prediction time is strictly BEFORE the forward transfer occurs (tx.occurred_at - 1us).
    The forward transfer itself is strictly excluded from graph feature computation and
    is used solely as the target label.
    """
    from datetime import timedelta

    feature_rows: list[list[float]] = []
    labels: list[int] = []

    for world in worlds:
        graph = TemporalGraph()
        graph.build_case(world.transactions)
        inst_map = {a.account_id: a.institution for a in world.accounts if a.institution}
        all_acc_ids = [a.account_id for a in world.accounts]

        for truth in world.truths:
            if not truth.intended_next_hop_label:
                continue

            for src_id, target in truth.intended_next_hop_label.items():
                targets = [target] if isinstance(target, str) else list(target)
                forward_txs = [
                    tx for tx in world.transactions
                    if tx.sender.account_id == src_id and tx.receiver.account_id in targets
                ]
                if not forward_txs:
                    continue

                # Prediction time: strictly BEFORE forward transfer occurs
                pred_time = forward_txs[0].occurred_at - timedelta(microseconds=1)

                for cand_id in all_acc_ids:
                    if cand_id == src_id:
                        continue
                    feats = extract_next_hop_candidate_features(
                        graph=graph,
                        source_id=src_id,
                        candidate_id=cand_id,
                        as_of_time=pred_time,
                        institution_map=inst_map,
                    )
                    feature_rows.append([feats[name] for name in NEXT_HOP_FEATURE_NAMES])
                    labels.append(1 if cand_id in targets else 0)

    X = np.array(feature_rows, dtype=np.float32)
    y = np.array(labels, dtype=np.int32)
    return X, y


# ── Metric Computation ───────────────────────────────────────────────────────


def evaluate_risk_metrics(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    threshold: float = 0.5,
) -> RiskEvaluationMetrics:
    """Compute precision, recall, f1, roc-auc, pr-auc, brier score, and confusion matrix."""
    if len(y_true) == 0:
        raise ValueError("y_true cannot be empty.")

    y_pred = (y_proba >= threshold).astype(int)
    pos_count = int(np.sum(y_true))
    neg_count = int(len(y_true) - pos_count)

    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    brier = float(brier_score_loss(y_true, y_proba))

    if pos_count > 0:
        precision = round(float(precision_score(y_true, y_pred, zero_division=0)), 4)
        recall = round(float(recall_score(y_true, y_pred, zero_division=0)), 4)
        f1 = round(float(f1_score(y_true, y_pred, zero_division=0)), 4)
    else:
        # Mathematically undefined for positive class when positive instances are 0
        precision = None
        recall = None
        f1 = None

    if len(np.unique(y_true)) > 1:
        roc_auc = round(float(roc_auc_score(y_true, y_proba)), 4)
        pr_auc = round(float(average_precision_score(y_true, y_proba)), 4)
    else:
        roc_auc = None
        pr_auc = None

    return RiskEvaluationMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        roc_auc=roc_auc,
        pr_auc=pr_auc,
        brier_score=round(brier, 4),
        confusion_matrix={
            "tp": int(tp),
            "fp": int(fp),
            "tn": int(tn),
            "fn": int(fn),
        },
        sample_count=len(y_true),
        positive_count=pos_count,
        negative_count=neg_count,
    )


def evaluate_cold_start_comparison(
    model: MuleRiskModel,
    X_test: np.ndarray,
    y_test: np.ndarray,
    is_cold_mask: np.ndarray,
) -> ColdStartComparisonMetrics:
    """Evaluate cold-start resilience via cohort comparison and historical masking stress-test."""
    # 1. Unmasked evaluation on full test set
    y_proba_unmasked = model.predict_proba(X_test)[:, 1]
    unmasked_metrics = evaluate_risk_metrics(y_test, y_proba_unmasked)

    # 2. Masked evaluation: forcefully zero out historical telemetry
    X_masked = X_test.copy()
    hist_feat_names = [
        "historical_tx_count",
        "historical_duration_seconds",
        "has_historical_profile",
        "is_cold_start",
        "evidence_maturity_level",
    ]
    for name in hist_feat_names:
        idx = ACCOUNT_FEATURE_NAMES.index(name)
        if name == "is_cold_start":
            X_masked[:, idx] = 1.0
        elif name == "evidence_maturity_level":
            X_masked[:, idx] = 1.0  # flow-dominant
        else:
            X_masked[:, idx] = 0.0

    y_proba_masked = model.predict_proba(X_masked)[:, 1]
    masked_metrics = evaluate_risk_metrics(y_test, y_proba_masked)
    masking_degradation = round(
        (unmasked_metrics.f1 or 0.0) - (masked_metrics.f1 or 0.0), 4
    )

    # 3. Cohort breakdown (accounts with pre-incident baseline vs zero baseline)
    rich_idx = ~is_cold_mask
    cold_idx = is_cold_mask

    cohort_rich = evaluate_risk_metrics(y_test[rich_idx], y_proba_unmasked[rich_idx]) if np.any(rich_idx) else None
    cohort_cold = evaluate_risk_metrics(y_test[cold_idx], y_proba_unmasked[cold_idx]) if np.any(cold_idx) else None

    cohort_deg = None
    if cohort_rich is not None and cohort_cold is not None:
        if cohort_rich.f1 is not None and cohort_cold.f1 is not None:
            cohort_deg = round(cohort_rich.f1 - cohort_cold.f1, 4)

    return ColdStartComparisonMetrics(
        unmasked_metrics=unmasked_metrics,
        masked_metrics=masked_metrics,
        masking_degradation_f1=masking_degradation,
        cohort_history_rich=cohort_rich,
        cohort_cold_start=cohort_cold,
        cohort_degradation_f1=cohort_deg,
    )


def evaluate_negative_control(
    model: MuleRiskModel,
    world: SyntheticWorld,
    threshold: float = 0.5,
) -> NegativeControlMetrics:
    """Evaluate risk model on the benign high-volume merchant scenario."""
    # Find benign merchant scenario
    merchant_truth = None
    for truth in world.truths:
        if truth.scenario_type == "benign_high_volume_merchant":
            merchant_truth = truth
            break

    if merchant_truth is None:
        raise ValueError("No benign_high_volume_merchant scenario found in provided world.")

    graph = TemporalGraph()
    graph.build_case(world.transactions)
    inst_map = {a.account_id: a.institution for a in world.accounts if a.institution}

    merchant_id = merchant_truth.metadata.get("merchant_account")
    if not merchant_id:
        for acc in world.accounts:
            if "merchant" in acc.account_id:
                merchant_id = acc.account_id
                break

    # Extract all accounts connected to this benign scenario
    prefix = merchant_truth.scenario_id
    scenario_accounts = [a for a in world.accounts if a.account_id.startswith(prefix)]

    flagged_count = 0
    merchant_score = 0.0

    max_t = max(t.occurred_at for t in world.transactions if t.sender.account_id.startswith(prefix) or t.receiver.account_id.startswith(prefix))

    for acc in scenario_accounts:
        pred = model.predict_risk(
            graph=graph,
            account_id=acc.account_id,
            as_of_time=max_t,
            institution_map=inst_map,
        )
        if pred.risk_score >= threshold:
            flagged_count += 1
        if acc.account_id == merchant_id:
            merchant_score = pred.risk_score

    fpr = float(flagged_count) / max(1, len(scenario_accounts))

    return NegativeControlMetrics(
        scenario_type="benign_high_volume_merchant",
        total_accounts=len(scenario_accounts),
        flagged_accounts=flagged_count,
        false_positive_rate=round(fpr, 4),
        merchant_risk_score=round(merchant_score, 4),
        merchant_account_id=str(merchant_id),
    )


def evaluate_next_hop(
    predictor: NextHopPredictor,
    worlds: Sequence[SyntheticWorld],
    top_k: int = 5,
) -> NextHopEvaluationMetrics:
    """Evaluate next-hop prediction on Top-1, Top-3, and MRR metrics.

    Strict Temporal Causality:
    Prediction is evaluated at (forward_tx.occurred_at - 1us), guaranteeing that
    the forward transaction to the target has NOT yet occurred in the graph.
    The candidate pool spans all candidate accounts in the network.
    """
    from datetime import timedelta

    top_1_hits = 0
    top_3_hits = 0
    reciprocal_ranks: list[float] = []
    total_evals = 0

    for world in worlds:
        graph = TemporalGraph()
        graph.build_case(world.transactions)
        inst_map = {a.account_id: a.institution for a in world.accounts if a.institution}
        all_acc_ids = [a.account_id for a in world.accounts]

        for truth in world.truths:
            if not truth.intended_next_hop_label:
                continue

            for src_id, target in truth.intended_next_hop_label.items():
                targets = [target] if isinstance(target, str) else list(target)
                forward_txs = [
                    tx for tx in world.transactions
                    if tx.sender.account_id == src_id and tx.receiver.account_id in targets
                ]
                if not forward_txs:
                    continue

                # Prediction time: strictly BEFORE forward transfer occurs
                pred_time = forward_txs[0].occurred_at - timedelta(microseconds=1)
                candidate_pool = [c for c in all_acc_ids if c != src_id]

                prediction = predictor.predict_next_hop(
                    graph=graph,
                    source_account_id=src_id,
                    as_of_time=pred_time,
                    candidate_pool=candidate_pool,
                    institution_map=inst_map,
                    top_k=len(candidate_pool),  # rank all candidates for true MRR
                )

                ranked_ids = [c.account_id for c in prediction.candidates]
                total_evals += 1

                # Check hits
                # Top-1
                if ranked_ids and ranked_ids[0] in targets:
                    top_1_hits += 1

                # Top-3
                if any(cand_id in targets for cand_id in ranked_ids[:3]):
                    top_3_hits += 1

                # Reciprocal rank across full candidate pool
                rr = 0.0
                for rank_idx, cand_id in enumerate(ranked_ids, start=1):
                    if cand_id in targets:
                        rr = 1.0 / float(rank_idx)
                        break
                reciprocal_ranks.append(rr)

    if total_evals == 0:
        return NextHopEvaluationMetrics(
            top_1_accuracy=0.0,
            top_3_accuracy=0.0,
            mean_reciprocal_rank=0.0,
            sample_count=0,
        )

    top_1_acc = float(top_1_hits) / float(total_evals)
    top_3_acc = float(top_3_hits) / float(total_evals)
    mrr = float(np.mean(reciprocal_ranks))

    return NextHopEvaluationMetrics(
        top_1_accuracy=round(top_1_acc, 4),
        top_3_accuracy=round(top_3_acc, 4),
        mean_reciprocal_rank=round(mrr, 4),
        sample_count=total_evals,
    )
