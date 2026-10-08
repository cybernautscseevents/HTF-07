"""
Shared fixtures for ML unit tests.
==================================

Ensures ML tests are completely self-contained, reproducible, and deterministic
on clean checkouts without requiring committed binary model artifacts.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from backend.app.ml.evaluation import (
    create_next_hop_dataset_from_worlds,
    create_risk_dataset_from_worlds,
)
from backend.app.ml.next_hop import NextHopPredictor
from backend.app.ml.risk_model import MuleRiskModel
from scripts.generator import generate_synthetic_world


@pytest.fixture(scope="session")
def trained_risk_model() -> MuleRiskModel:
    """Session fixture providing a deterministically trained MuleRiskModel.

    Loads from disk if available, or trains in-memory on reproducible synthetic worlds.
    """
    model_path = Path("backend/models/artefacts/mule_risk_model.joblib")
    if model_path.exists():
        try:
            return MuleRiskModel.load(model_path)
        except Exception:
            pass

    # Deterministic in-memory training on synthetic worlds
    train_worlds = [generate_synthetic_world(seed=s) for s in [42, 101, 102, 103]]
    X, y, _, _ = create_risk_dataset_from_worlds(train_worlds)
    model = MuleRiskModel(random_state=42)
    model.fit(X, y)
    return model


@pytest.fixture(scope="session")
def next_hop_predictor() -> NextHopPredictor:
    """Session fixture providing a deterministically trained NextHopPredictor.

    Loads from disk if available, or trains in-memory on reproducible synthetic worlds.
    """
    model_path = Path("backend/models/artefacts/next_hop_predictor.joblib")
    if model_path.exists():
        try:
            return NextHopPredictor.load(model_path)
        except Exception:
            pass

    train_worlds = [generate_synthetic_world(seed=s) for s in [42, 101, 102, 103]]
    X, y = create_next_hop_dataset_from_worlds(train_worlds)
    predictor = NextHopPredictor(random_state=42)
    predictor.fit(X, y)
    return predictor
