"""Pydantic schemas for the investigation analysis API endpoint.

Endpoint: POST /api/cases/{case_id}/analyze
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum, unique
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


@unique
class StageExecutionStatus(StrEnum):
    """Operational status of an individual analytical stage."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INFEASIBLE = "infeasible"
    FAILED = "failed"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class TaintSeedInput(BaseModel):
    """Explicit fraud transaction seed specification."""

    model_config = ConfigDict(frozen=True)

    transaction_id: str = Field(
        ...,
        min_length=1,
        description="Transaction ID belonging to the case where illicit proceeds were injected.",
    )
    tainted_amount_minor_units: int = Field(
        ...,
        gt=0,
        description="Modeled tainted capital in integer minor units (paise for INR).",
    )


class ForecastConfigInput(BaseModel):
    """Bounded configuration for next-hop forecast trajectory generation."""

    model_config = ConfigDict(frozen=True)

    top_k: int = Field(default=3, ge=1, le=10, description="Beam width / max branches per hop.")
    max_depth: int = Field(default=3, ge=1, le=5, description="Maximum predicted future hops.")
    hop_delay_seconds: float = Field(
        default=300.0,
        gt=0.0,
        description="Inter-hop simulated dwell latency in seconds.",
    )


class OptimizationConstraintsInput(BaseModel):
    """Hard policy constraints for Pareto intervention ranking."""

    model_config = ConfigDict(frozen=True)

    minimum_required_illicit_recovery: int = Field(
        default=0,
        ge=0,
        description="Minimum acceptable illicit capital interception in minor units.",
    )
    maximum_legitimate_capital_affected: int | None = Field(
        default=None,
        ge=0,
        description="Maximum tolerable legitimate collateral in minor units.",
    )
    maximum_affected_accounts: int | None = Field(
        default=None,
        ge=0,
        description="Maximum number of accounts permitted to be affected.",
    )
    maximum_affected_edges: int | None = Field(
        default=None,
        ge=0,
        description="Maximum number of transaction edges permitted to be blocked.",
    )
    maximum_interventions: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Maximum intervention actions permitted.",
    )
    minimum_provenance_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum required provenance confidence score.",
    )


class InvestigationAnalysisRequest(BaseModel):
    """Payload for POST /api/cases/{case_id}/analyze."""

    model_config = ConfigDict(frozen=True)

    simulation_timestamp: datetime = Field(
        ...,
        description="Decision timestamp T (timezone-aware UTC). Events <= T are historical facts.",
    )
    taint_seeds: list[TaintSeedInput] = Field(
        ...,
        min_length=1,
        description="Explicit fraud proceeds injections for provenance propagation.",
    )
    sink_account_ids: list[str] | None = Field(
        default=None,
        description="Optional cash-out destination accounts for temporal min-cut chokepoint search.",
    )
    source_account_ids: list[str] | None = Field(
        default=None,
        description="Optional explicit fraud source accounts (defaults to seed receivers).",
    )
    eligible_event_ids: list[str] | None = Field(
        default=None,
        description="Optional explicit event IDs permitted for intervention hold candidates.",
    )
    forecast_config: ForecastConfigInput | None = Field(
        default=None,
        description="Optional configuration for future trajectory generation.",
    )
    constraints: OptimizationConstraintsInput | None = Field(
        default=None,
        description="Optional policy constraints for intervention optimization.",
    )


# ── Response Models ──────────────────────────────────────────────────────────


class StageReport(BaseModel):
    """Execution status and diagnostics for one analysis stage."""

    model_config = ConfigDict(frozen=True)

    status: StageExecutionStatus
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class GraphSummary(BaseModel):
    """Summary of the case-specific temporal multigraph."""

    model_config = ConfigDict(frozen=True)

    node_count: int
    edge_count: int
    account_ids: list[str]


class TaintSummary(BaseModel):
    """Summary of deterministic taint propagation."""

    model_config = ConfigDict(frozen=True)

    seed_count: int
    allocated_edge_count: int
    current_tainted_account_count: int
    total_propagated_volume_minor_units: int
    shortfall_count: int
    current_tainted_accounts: list[str]


class ChokepointReport(BaseModel):
    """Summary of temporal chokepoint min-cut search."""

    model_config = ConfigDict(frozen=True)

    status: str
    cut_size: int
    cut_event_ids: list[str]
    total_encoded_cut_cost: int
    total_estimated_collateral_minor_units: int
    is_cut_verified: bool
    explanation_summary: str | None = None


class ForecastReport(BaseModel):
    """Summary of forecast-aware future scenario generation."""

    model_config = ConfigDict(frozen=True)

    status: str
    paths_generated_count: int
    scenarios_evaluated_count: int


class CandidateRecommendation(BaseModel):
    """Structured Pareto-optimal intervention recommendation."""

    model_config = ConfigDict(frozen=True)

    intervention_id: str
    intervention_type: str
    target_account_id: str | None = None
    target_event_id: str | None = None
    modeled_tainted_capital_intercepted: int
    modeled_legitimate_capital_affected: int
    remaining_downstream_taint: int
    number_of_affected_edges: int
    number_of_affected_accounts: int
    provenance_confidence: float
    recovery_efficiency: str
    policy_feasible: bool
    explanation: str


class EvaluatedCandidateSummary(BaseModel):
    """Aggregated metrics across all evaluated intervention candidates."""

    model_config = ConfigDict(frozen=True)

    total_candidates_count: int
    feasible_candidates_count: int
    infeasible_candidates_count: int
    pareto_frontier_size: int


class InvestigationAnalysisResponse(BaseModel):
    """Complete, dashboard-ready output of an end-to-end investigation analysis."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    simulation_timestamp: datetime
    analysis_timestamp: datetime
    overall_status: str
    stages: dict[str, StageReport]
    graph_summary: GraphSummary
    taint_summary: TaintSummary
    risk_predictions: list[dict[str, Any]]
    next_hop_predictions: list[dict[str, Any]]
    forecast_report: ForecastReport
    chokepoint_report: ChokepointReport | None = None
    evaluated_candidates: EvaluatedCandidateSummary
    selected_recommendation: CandidateRecommendation | None = None
    warnings_and_limitations: list[str]
