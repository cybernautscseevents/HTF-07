# ML Environment Verification

## Overview

This document records the verification of the machine learning environment for the **AEGIS-Flow** hackathon project. The scope is strictly environment verification: validating Python 3.13.x compatibility, verifying core ML package imports from `backend/requirements.txt`, executing an in-memory synthetic LightGBM smoke test, and verifying inference determinism.

No application logic, external datasets, or real fraud features were added.

---

## 1. Python Environment

- **Python Version**: `Python 3.13.12` (`CPython 3.13.12-macos-aarch64-none`)
- **Virtual Environment Location**: `.venv/` (created via `uv venv --python 3.13 .venv`)
- **Dependency Source**: `backend/requirements.txt` (no secondary requirements file created)

---

## 2. ML Package Versions

All packages were resolved and installed directly against `backend/requirements.txt`:

| Package | Specified in `requirements.txt` | Installed Version | Status |
| :--- | :--- | :--- | :--- |
| **NumPy** | `>=1.26,<3.0` | `2.5.3` | Installed & Verified |
| **Pandas** | `>=2.1,<3.0` | `2.3.3` | Installed & Verified |
| **Scikit-Learn** | `>=1.4,<2.0` | `1.9.1` | Installed & Verified |
| **LightGBM** | `>=4.0,<5.0` | `4.7.0` | Installed & Verified |

*Note: Additional core project dependencies from `backend/requirements.txt` (such as `rustworkx==0.18.1`, `fastapi==0.142.4`, `pydantic==2.13.5`, `sqlalchemy==2.1.4`, `redis==8.1.0`) were also resolved and imported without error.*

---

## 3. Import Verification

All required imports were verified using the virtual environment interpreter (`.venv/bin/python`):

```bash
.venv/bin/python -c "
import numpy as np
import pandas as pd
import sklearn
import lightgbm as lgb
print('numpy:', np.__version__)
print('pandas:', pd.__version__)
print('scikit-learn:', sklearn.__version__)
print('lightgbm:', lgb.__version__)
"
```

**Output:**
```text
numpy: 2.5.3
pandas: 2.3.3
scikit-learn: 1.9.1
lightgbm: 4.7.0
```

---

## 4. In-Memory Synthetic Smoke Test

### Test Design
- **Dataset**: In-memory synthetic tabular data generated via NumPy's default RNG (`seed=42`).
  - Training set: 30 samples, 3 continuous/discrete features (`x1`, `x2`, `x3`), binary target `y = (x1 + x2 > 0)`.
  - Test set: 5 samples (`x1`, `x2`, `x3`).
  - No external files or datasets required.
- **Model**: `lightgbm.LGBMClassifier`
  - Hyperparameters: `n_estimators=10`, `max_depth=3`, `num_leaves=7`, `min_child_samples=5`, `random_state=42`, `verbosity=-1`, `deterministic=True`, `force_col_wise=True`.
- **Validation**:
  - Training completes without errors.
  - Predicts discrete binary labels (`0` / `1`).
  - Predicts continuous class probabilities.
  - Executed twice with the same seed to test determinism.

### Smoke Test Output

```text
--- Smoke Test Run 1 ---
Predicted labels: [1, 1, 1, 0, 0]
Predicted probabilities:
 [[0.17392986 0.82607014]
 [0.19438919 0.80561081]
 [0.17392986 0.82607014]
 [0.82462185 0.17537815]
 [0.79379926 0.20620074]]

--- Smoke Test Run 2 ---
Predicted labels: [1, 1, 1, 0, 0]
Predicted probabilities:
 [[0.17392986 0.82607014]
 [0.19438919 0.80561081]
 [0.17392986 0.82607014]
 [0.82462185 0.17537815]
 [0.79379926 0.20620074]]
```

---

## 5. Determinism Verification

- **Label Equivalence**: `np.array_equal(preds_run1, preds_run2)` evaluated to `True`.
- **Probability Equivalence**: `np.allclose(probs_run1, probs_run2)` evaluated to `True`.
- **Result**: **PASSED**. Repeated execution with fixed random seeds produces bit-for-bit identical predictions and probability distributions.

---

## 6. Machine-Specific Observations & Resolutions

- **Platform**: macOS 26.x (Apple Silicon / `arm64`)
- **OpenMP Runtime (`libomp.dylib`) Dependency for LightGBM**:
  - On macOS, LightGBM dynamically links against `@rpath/libomp.dylib`.
  - If Homebrew's `libomp` is not installed or brew is inaccessible (e.g. pending Xcode license acceptance), LightGBM raises an `OSError: dlopen(...): Library not loaded: @rpath/libomp.dylib`.
  - **Resolution**: `scikit-learn` includes an arm64-compatible OpenMP dynamic library in its package (`.venv/lib/python3.13/site-packages/sklearn/.dylibs/libomp.dylib`). Linking this library to `/opt/homebrew/opt/libomp/lib/libomp.dylib` and the Python library search path immediately satisfied LightGBM's runtime requirements without requiring root access or external package managers.
  - On standard macOS developer setups, running `brew install libomp` also satisfies this requirement. On Linux / Docker environments, standard `libgomp1` (`apt-get install libgomp1`) satisfies it.
