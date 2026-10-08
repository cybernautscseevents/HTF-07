"""
Evaluate AEGIS-Flow ML Intelligence Models
==========================================

Runs full evaluation on out-of-sample test scenarios and prints
empirical metrics:
1. Mule Risk Model (Precision, Recall, F1, ROC-AUC, PR-AUC, Brier score, Confusion Matrix)
2. Cold-Start Cohort vs. History-Rich Cohort Comparison
3. Next-Hop Destination Prediction (Top-1, Top-3, MRR)
4. Negative Control Evaluation (Benign High-Volume Merchant False Positive Rate)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.ml.evaluation import (
    create_risk_dataset_from_worlds,
    evaluate_cold_start_comparison,
    evaluate_negative_control,
    evaluate_next_hop,
    evaluate_risk_metrics,
)
from backend.app.ml.next_hop import NextHopPredictor
from backend.app.ml.risk_model import MuleRiskModel
from scripts.generator import generate_synthetic_world


def evaluate_pipeline(
    test_seeds: list[int] = [201, 202, 203],
    model_dir: Path = REPO_ROOT / "backend" / "models" / "artefacts",
    output_json: Path | None = None,
) -> dict:
    """Run empirical evaluation and return structured metrics."""
    # 1. Load models
    risk_path = model_dir / "mule_risk_model.joblib"
    nh_path = model_dir / "next_hop_predictor.joblib"

    if not risk_path.exists() or not nh_path.exists():
        print("Model artifacts not found. Training models first...")
        from scripts.train_models import train_models
        train_models(output_dir=model_dir)

    risk_model = MuleRiskModel.load(risk_path)
    next_hop_model = NextHopPredictor.load(nh_path)

    print(f"\n=======================================================")
    print(f"AEGIS-FLOW ML EVALUATION REPORT")
    print(f"Test Seeds: {test_seeds}")
    print(f"=======================================================\n")

    # 2. Generate out-of-sample test worlds
    test_worlds = [generate_synthetic_world(seed=s) for s in test_seeds]

    # 3. Evaluate Mule Risk Model
    print("--- 1. Mule Risk Classification ---")
    X_test, y_test, _, is_cold_mask = create_risk_dataset_from_worlds(test_worlds)
    y_proba = risk_model.predict_proba(X_test)[:, 1]

    risk_metrics = evaluate_risk_metrics(y_test, y_proba)
    print(f"Sample Count:     {risk_metrics.sample_count} (Positives={risk_metrics.positive_count}, Negatives={risk_metrics.negative_count})")
    print(f"Precision:        {risk_metrics.precision:.4f}" if risk_metrics.precision is not None else "Precision:        Undefined")
    print(f"Recall:           {risk_metrics.recall:.4f}" if risk_metrics.recall is not None else "Recall:           Undefined")
    print(f"F1 Score:         {risk_metrics.f1:.4f}" if risk_metrics.f1 is not None else "F1 Score:         Undefined")
    print(f"ROC-AUC:          {risk_metrics.roc_auc:.4f}" if risk_metrics.roc_auc is not None else "ROC-AUC:          Undefined")
    print(f"PR-AUC:           {risk_metrics.pr_auc:.4f}" if risk_metrics.pr_auc is not None else "PR-AUC:           Undefined")
    print(f"Brier Score:      {risk_metrics.brier_score:.4f}")
    print(f"Confusion Matrix: TP={risk_metrics.confusion_matrix['tp']}, FP={risk_metrics.confusion_matrix['fp']}, "
          f"TN={risk_metrics.confusion_matrix['tn']}, FN={risk_metrics.confusion_matrix['fn']}")

    # 4. Evaluate Cold-Start vs History-Rich Cohorts
    print("\n--- 2. Cold-Start Intelligence Analysis ---")
    cold_comp = evaluate_cold_start_comparison(risk_model, X_test, y_test, is_cold_mask)
    print("Historical Masking Stress-Test (Forcefully wiping all prior history):")
    unmasked_f1_str = f"{cold_comp.unmasked_metrics.f1:.4f}" if cold_comp.unmasked_metrics.f1 is not None else "Undefined"
    masked_f1_str = f"{cold_comp.masked_metrics.f1:.4f}" if cold_comp.masked_metrics.f1 is not None else "Undefined"
    print(f"  Unmasked F1:         {unmasked_f1_str} | PR-AUC: {cold_comp.unmasked_metrics.pr_auc:.4f}")
    print(f"  Masked F1:           {masked_f1_str} | PR-AUC: {cold_comp.masked_metrics.pr_auc:.4f}")
    print(f"  Degradation on Mask: {cold_comp.masking_degradation_f1:+.4f} (unmasked.f1 - masked.f1)")

    if cold_comp.cohort_history_rich and cold_comp.cohort_cold_start:
        rich = cold_comp.cohort_history_rich
        cold = cold_comp.cohort_cold_start
        print(f"\nCohort Breakdown:")
        print(f"  History-Rich Cohort (n={rich.sample_count}):")
        print(f"     Total samples:    {rich.sample_count}")
        print(f"     Positive samples: {rich.positive_count}")
        print(f"     Negative samples: {rich.negative_count}")
        if rich.positive_count == 0:
            print(f"     Precision/Recall/F1: Undefined (no positive samples in cohort; TN={rich.confusion_matrix['tn']}, FP={rich.confusion_matrix['fp']}, Specificity=100.0%)")
        else:
            print(f"     Precision={rich.precision:.4f}, Recall={rich.recall:.4f}, F1={rich.f1:.4f}")

        print(f"  Cold-Start Cohort (n={cold.sample_count}):")
        print(f"     Total samples:    {cold.sample_count}")
        print(f"     Positive samples: {cold.positive_count}")
        print(f"     Negative samples: {cold.negative_count}")
        cold_f1_str = f"{cold.f1:.4f}" if cold.f1 is not None else "Undefined"
        print(f"     Precision={cold.precision:.4f}, Recall={cold.recall:.4f}, F1={cold_f1_str}")
        if cold_comp.cohort_degradation_f1 is not None:
            print(f"  Cohort F1 Diff:      {cold_comp.cohort_degradation_f1:+.4f}")

    # 5. Evaluate Next-Hop Predictor
    print("\n--- 3. Next-Hop Destination Prediction ---")
    nh_metrics = evaluate_next_hop(next_hop_model, test_worlds, top_k=5)
    print(f"Evaluated Transitions: {nh_metrics.sample_count}")
    print(f"Top-1 Accuracy:        {nh_metrics.top_1_accuracy:.4f} ({nh_metrics.top_1_accuracy * 100:.1f}%)")
    print(f"Top-3 Accuracy:        {nh_metrics.top_3_accuracy:.4f} ({nh_metrics.top_3_accuracy * 100:.1f}%)")
    print(f"Mean Reciprocal Rank:  {nh_metrics.mean_reciprocal_rank:.4f}")

    # 6. Negative Control Evaluation (Benign High-Volume Merchant)
    print("\n--- 4. Negative Control: Benign High-Volume Merchant ---")
    control_metrics = evaluate_negative_control(risk_model, test_worlds[0])
    print(f"Scenario:             {control_metrics.scenario_type}")
    print(f"Merchant Account ID:  {control_metrics.merchant_account_id}")
    print(f"Merchant Risk Score:  {control_metrics.merchant_risk_score:.4f} (threshold=0.50)")
    print(f"Total Accounts:       {control_metrics.total_accounts}")
    print(f"False Positives:      {control_metrics.flagged_accounts}")
    print(f"False Positive Rate:  {control_metrics.false_positive_rate:.4f} ({control_metrics.false_positive_rate * 100:.1f}%)")

    report = {
        "test_seeds": test_seeds,
        "risk_model": risk_metrics.model_dump(),
        "cold_start": cold_comp.model_dump(),
        "next_hop": nh_metrics.model_dump(),
        "negative_control": control_metrics.model_dump(),
    }

    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        with open(output_json, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nSaved JSON report to {output_json}")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate AEGIS-Flow ML models.")
    parser.add_argument(
        "--test-seeds",
        nargs="+",
        type=int,
        default=[201, 202, 203],
        help="Random seeds for test world generation.",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=REPO_ROOT / "backend" / "models" / "artefacts",
        help="Directory with saved joblib model artifacts.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to output evaluation JSON.",
    )
    args = parser.parse_args()
    evaluate_pipeline(
        test_seeds=args.test_seeds,
        model_dir=args.model_dir,
        output_json=args.output_json,
    )


if __name__ == "__main__":
    main()
