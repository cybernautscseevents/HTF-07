"""Immutable data structures for counterfactual intervention simulation.

All model classes are frozen dataclasses.  Money fields use ``int``
(minor-unit) arithmetic exclusively — no floats are used for money.

The counterfactual engine never mutates these once constructed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum, unique


# ── Intervention type ────────────────────────────────────────────────────────


@unique
class InterventionType(StrEnum):
    """Supported counterfactual intervention kinds.

    * ``ACCOUNT_HOLD`` — block all future outbound flow from an account.
    * ``EDGE_HOLD`` — block a single future transaction edge.
    """

    ACCOUNT_HOLD = "account_hold"
    EDGE_HOLD = "edge_hold"


# ── Candidate ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class InterventionCandidate:
    """A proposed counterfactual intervention for simulation.

    Exactly one of ``target_account_id`` or ``target_event_id`` must be
    specified depending on ``intervention_type``.
    """

    intervention_type: InterventionType
    target_account_id: str | None = None
    target_event_id: str | None = None

    def __post_init__(self) -> None:
        if self.intervention_type == InterventionType.ACCOUNT_HOLD:
            if not self.target_account_id:
                raise ValueError(
                    "ACCOUNT_HOLD intervention requires a non-empty target_account_id."
                )
            if self.target_event_id is not None:
                raise ValueError(
                    "ACCOUNT_HOLD intervention must not specify target_event_id."
                )
        elif self.intervention_type == InterventionType.EDGE_HOLD:
            if not self.target_event_id:
                raise ValueError(
                    "EDGE_HOLD intervention requires a non-empty target_event_id."
                )
            if self.target_account_id is not None:
                raise ValueError(
                    "EDGE_HOLD intervention must not specify target_account_id."
                )


# ── Source-level contribution detail ─────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SourceInterceptionDetail:
    """Per-provenance-source breakdown of intercepted vs. residual taint."""

    source_id: str
    source_case_id: str
    intercepted_amount_minor_units: int
    residual_amount_minor_units: int


# ── Counterfactual result ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CounterfactualResult:
    """Complete output for one simulated counterfactual intervention.

    All money fields are in integer minor units.  ``modeled_tainted_capital_intercepted``
    and ``modeled_legitimate_capital_affected`` expose the raw trade-off
    components.  The optimizer (not yet implemented) will consume these
    independently — there is no single composite score here.

    ``provenance_coverage`` is the fraction of the intercepted taint that
    has explicit per-seed attribution (always 1.0 in the current engine
    because we never invent unattributed taint).

    ``provenance_confidence`` reflects whether the baseline taint result
    had any shortfalls among the affected accounts (1.0 if no shortfalls,
    degraded otherwise).
    """

    intervention_id: str
    intervention_type: InterventionType
    target_account_id: str | None
    target_event_id: str | None
    simulation_timestamp: datetime

    # ── Core trade-off components ────────────────────────────────────────
    modeled_tainted_capital_intercepted: int
    modeled_legitimate_capital_affected: int
    remaining_downstream_taint: int

    # ── Scope metrics ────────────────────────────────────────────────────
    number_of_affected_edges: int
    number_of_affected_accounts: int

    # ── Provenance quality ───────────────────────────────────────────────
    provenance_coverage: float
    provenance_confidence: float

    # ── Source-level detail ───────────────────────────────────────────────
    source_interception_details: tuple[SourceInterceptionDetail, ...]

    # ── Explanation ──────────────────────────────────────────────────────
    explanation: str
    blocked_event_ids: tuple[str, ...]
    affected_account_ids: tuple[str, ...]
