"""Deterministic modeled money-provenance and taint subsystem."""

from backend.app.taint.engine import TaintEngine
from backend.app.taint.models import (
    AccountTaintBalance,
    ObservableBalanceShortfall,
    SourceConservation,
    SourceContribution,
    TaintAllocation,
    TaintResult,
    TaintSeed,
)
from backend.app.taint.provenance import ProvenanceTrace, trace_for_source

__all__ = [
    "AccountTaintBalance",
    "ObservableBalanceShortfall",
    "ProvenanceTrace",
    "SourceConservation",
    "SourceContribution",
    "TaintAllocation",
    "TaintEngine",
    "TaintResult",
    "TaintSeed",
    "trace_for_source",
]
