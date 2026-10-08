"""Models used by the deterministic intervention benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from backend.app.counterfactual.models import InterventionCandidate
from backend.app.optimization.models import OptimizationConstraints


@dataclass(frozen=True, slots=True)
class BenchmarkScenario:
    """Inputs visible to every strategy at one evaluation timestamp."""

    scenario_id: str
    scenario_type: str
    simulation_timestamp: Any
    candidates: tuple[InterventionCandidate, ...]
    evaluations: tuple[Any, ...]
    constraints: OptimizationConstraints
    risk_scores: dict[str, Decimal]
    tainted_balances: dict[str, int]
    relevant_transaction_values: dict[str, int]
    cold_start: bool


@dataclass(frozen=True, slots=True)
class StrategyResult:
    """One strategy's selected intervention and measured outcomes."""

    strategy: str
    scenario_id: str
    selected_intervention_id: str | None
    feasible: bool
    illicit_capital_intercepted: int
    legitimate_capital_affected: int
    efficiency: Decimal | None
    illicit_per_rupee_legitimate: Decimal | None
    affected_accounts: int
    affected_edges: int
    intervention_count: int
    decision_latency_ms: Decimal
    pareto_efficient: bool
    tie_count: int
    reason: str


@dataclass(frozen=True, slots=True)
class AggregateResult:
    """Deterministic aggregate over scenario-level strategy results."""

    strategy: str
    scenarios: int
    feasible_recommendations: int
    recovery: int
    collateral: int
    efficiency: Decimal | None
    accounts: int
    edges: int
    runtime_ms: Decimal
    pareto_efficient_selections: int
    cold_start_scenarios: int


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """Results for every strategy on one scenario."""

    scenario_id: str
    scenario_type: str
    cold_start: bool
    strategies: tuple[StrategyResult, ...]
    findings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """Complete benchmark output, suitable for JSON serialization."""

    metadata: dict[str, Any]
    scenarios: tuple[ScenarioResult, ...]
    aggregates: tuple[AggregateResult, ...]
    strategy_definitions: dict[str, str]
    analysis: dict[str, Any]
    limitations: tuple[str, ...]
