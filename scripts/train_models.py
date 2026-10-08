"""
Train AEGIS-Flow ML Intelligence Models
=======================================

Reproducible training script for:
1. MuleRiskModel (LightGBM classifier with probability calibration)
2. NextHopPredictor (candidate affinity ranking model)

Saves trained model artifacts to `backend/models/artefacts/`.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.ml.evaluation import (
    create_next_hop_dataset_from_worlds,
    create_risk_dataset_from_worlds,
)
from backend.app.ml.next_hop import NextHopPredictor
from backend.app.ml.risk_model import MuleRiskModel
from scripts.generator import generate_synthetic_world


def train_models(
    train_seeds: list[int] = [42, 101, 102, 103],
    output_dir: Path = REPO_ROOT / "backend" / "models" / "artefacts",
) -> tuple[MuleRiskModel, NextHopPredictor]:
    """Train risk and next-hop models deterministically on multi-seed synthetic worlds."""
    print(f"Generating synthetic training worlds for seeds: {train_seeds}...")
    train_worlds = [generate_synthetic_world(seed=s) for s in train_seeds]

    # 1. Train MuleRiskModel
    print("Building account risk training matrix...")
    X_risk, y_risk, _, _ = create_risk_dataset_from_worlds(train_worlds)
    print(f"Risk dataset shape: X={X_risk.shape}, positives={sum(y_risk)}, negatives={len(y_risk) - sum(y_risk)}")

    risk_model = MuleRiskModel(random_state=42)
    print("Fitting calibrated MuleRiskModel...")
    risk_model.fit(X_risk, y_risk)

    risk_path = output_dir / "mule_risk_model.joblib"
    risk_model.save(risk_path)
    print(f"Saved MuleRiskModel to {risk_path}")

    # 2. Train NextHopPredictor
    print("Building next-hop pairwise training dataset...")
    X_nh, y_nh = create_next_hop_dataset_from_worlds(train_worlds)
    print(f"Next-hop dataset shape: X={X_nh.shape}, positives={sum(y_nh)}, negatives={len(y_nh) - sum(y_nh)}")

    next_hop_model = NextHopPredictor(random_state=42)
    print("Fitting NextHopPredictor...")
    next_hop_model.fit(X_nh, y_nh)

    nh_path = output_dir / "next_hop_predictor.joblib"
    next_hop_model.save(nh_path)
    print(f"Saved NextHopPredictor to {nh_path}")

    print("Model training successfully completed!")
    return risk_model, next_hop_model


def main() -> None:
    parser = argparse.ArgumentParser(description="Train AEGIS-Flow ML intelligence models.")
    parser.add_argument(
        "--train-seeds",
        nargs="+",
        type=int,
        default=[42, 101, 102, 103],
        help="Random seeds for synthetic world generation.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "backend" / "models" / "artefacts",
        help="Directory to save joblib model artifacts.",
    )
    args = parser.parse_args()
    train_models(train_seeds=args.train_seeds, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
