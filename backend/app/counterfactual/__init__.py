"""
AEGIS-Flow — Counterfactual Intervention Simulator
===================================================

Deterministic counterfactual simulation engine that evaluates:

    "What would happen to the modeled illicit-money flow
     if we intervened at a particular account or transaction edge?"

The simulator compares the actual observed/current taint flow against
one or more counterfactual worlds in which a candidate intervention is
applied.  It does NOT mutate the baseline graph or taint result.

Public API
----------
* :class:`InterventionType` — enum of supported intervention kinds.
* :class:`InterventionCandidate` — a proposed counterfactual action.
* :class:`CounterfactualResult` — output for one simulated intervention.
* :class:`CounterfactualSimulator` — the simulation engine.
* :func:`generate_candidates` — derive candidates from taint state.
"""

from backend.app.counterfactual.models import (
    CounterfactualResult,
    InterventionCandidate,
    InterventionType,
)
from backend.app.counterfactual.simulator import CounterfactualSimulator
from backend.app.counterfactual.candidates import generate_candidates

__all__ = [
    "CounterfactualResult",
    "CounterfactualSimulator",
    "InterventionCandidate",
    "InterventionType",
    "generate_candidates",
]
