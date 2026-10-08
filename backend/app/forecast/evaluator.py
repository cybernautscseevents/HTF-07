"""Forecast-aware counterfactual evaluator conforming to CounterfactualEvaluator protocol.

Evaluates intervention candidates across a bounded set of plausible predicted
future worlds rather than a single observed future.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
from time import perf_counter
from typing import Sequence

from backend.app.counterfactual.models import (
    CounterfactualResult,
    InterventionCandidate,
    InterventionType,
    SourceInterceptionDetail,
)
from backend.app.counterfactual.simulator import CounterfactualSimulator
from backend.app.forecast.candidates import generate_forecast_candidates
from backend.app.forecast.generator import (
    ForecastGeneratorConfig,
    ForecastPath,
    ForecastPathGenerator,
    ForecastScenario,
)
from backend.app.forecast.models import (
    ForecastAwareCounterfactualResult,
    ForecastStatus,
    ScenarioEvaluationDetail,
)
from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.ml.next_hop import NextHopPredictor
from backend.app.taint.engine import TaintEngine
from backend.app.taint.models import TaintResult, TaintSeed


def _deterministic_intervention_id(
    candidate: InterventionCandidate,
    sim_time: datetime,
) -> str:
    target = candidate.target_account_id or candidate.target_event_id or ""
    raw = f"forecast:{candidate.intervention_type.value}:{target}:{sim_time.isoformat()}"
    return f"cf-fc-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


class ForecastAwareCounterfactualEvaluator:
    """Multi-future counterfactual evaluator conforming to CounterfactualEvaluator protocol."""

    def __init__(
        self,
        graph: TemporalGraph,
        taint_seeds: Sequence[TaintSeed],
        simulation_timestamp: datetime,
        predictor: NextHopPredictor | None = None,
        config: ForecastGeneratorConfig | None = None,
        candidate_pool: Sequence[str] | None = None,
        institution_map: dict[str, str] | None = None,
    ) -> None:
        if simulation_timestamp.tzinfo is None:
            raise ValueError("simulation_timestamp must be timezone-aware.")

        self.graph = graph
        self.taint_seeds = tuple(taint_seeds)
        self.simulation_timestamp = simulation_timestamp
        self.predictor = predictor or NextHopPredictor()
        self.config = config or ForecastGeneratorConfig()
        self.candidate_pool = candidate_pool
        self.institution_map = institution_map

        # Measure forecast generation runtime
        start_time = perf_counter()

        # Build isolated historical graph <= simulation_timestamp
        self.historical_graph = TemporalGraph()
        for edge in self.graph.events_between(end=simulation_timestamp, active_only=True):
            from contracts.account import AccountReference
            from contracts.transaction import TransactionEvent

            self.historical_graph.add_event(
                TransactionEvent(
                    event_id=edge.event_id,
                    transaction_id=edge.transaction_id,
                    sender=AccountReference(account_id=edge.sender_id),
                    receiver=AccountReference(account_id=edge.receiver_id),
                    amount_minor_units=edge.amount_minor_units,
                    currency=edge.currency,
                    occurred_at=edge.occurred_at,
                    observed_at=edge.observed_at,
                    status=edge.status,
                    channel=edge.channel,
                    origin=edge.origin,
                )
            )

        # Filter seeds to transactions that actually occurred <= simulation_timestamp
        active_historical_tx_ids = {
            edge.transaction_id
            for edge in self.historical_graph.events_between(active_only=True)
        }
        self.historical_seeds = tuple(
            seed for seed in self.taint_seeds
            if seed.transaction_id in active_historical_tx_ids
        )

        # Compute taint state at T
        if self.historical_seeds:
            self.taint_at_t: TaintResult = TaintEngine().run(
                self.historical_graph, list(self.historical_seeds)
            )
        else:
            self.taint_at_t = TaintEngine().run(self.historical_graph, [])

        # Active sources holding positive tainted balances at T
        self.active_sources = {
            bal.account_id: bal.tainted_balance_minor_units
            for bal in self.taint_at_t.current_tainted_accounts()
            if bal.tainted_balance_minor_units > 0
        }

        # Generate paths and scenarios
        self.generator = ForecastPathGenerator(
            predictor=self.predictor,
            config=self.config,
        )

        self.paths: tuple[ForecastPath, ...] = self.generator.generate_paths(
            graph=self.historical_graph,
            active_sources=self.active_sources,
            simulation_timestamp=self.simulation_timestamp,
            candidate_pool=self.candidate_pool,
            institution_map=self.institution_map,
        )

        self.scenarios: tuple[ForecastScenario, ...] = self.generator.build_future_scenarios(
            historical_graph=self.historical_graph,
            paths=self.paths,
            taint_seeds=self.historical_seeds,
            simulation_timestamp=self.simulation_timestamp,
        )

        self.forecast_generation_runtime_ms = Decimal(
            str((perf_counter() - start_time) * 1000)
        )

        # Determine forecast status
        if not self.active_sources or not self.scenarios:
            self.forecast_status = (
                ForecastStatus.NO_CANDIDATE_PATHS.value
                if self.active_sources
                else ForecastStatus.INSUFFICIENT_EVIDENCE.value
            )
        else:
            self.forecast_status = ForecastStatus.READY.value

        # Pre-instantiate CounterfactualSimulator for each future world
        self._simulators: dict[str, CounterfactualSimulator] = {
            s.scenario_id: CounterfactualSimulator(s.graph, s.baseline_taint)
            for s in self.scenarios
        }

    def generate_candidates(
        self, include_edge_holds: bool = False
    ) -> list[InterventionCandidate]:
        """Generate visible intervention candidates for this forecast evaluation."""
        return generate_forecast_candidates(
            graph=self.historical_graph,
            taint_at_t=self.taint_at_t,
            simulation_timestamp=self.simulation_timestamp,
            scenarios=self.scenarios,
            include_edge_holds=include_edge_holds,
        )

    def evaluate(
        self, candidate: InterventionCandidate, simulation_timestamp: datetime
    ) -> CounterfactualResult:
        """Evaluate one candidate intervention across all plausible futures.

        Implements the CounterfactualEvaluator protocol.
        """
        intervention_id = _deterministic_intervention_id(candidate, simulation_timestamp)

        # Handle failure / insufficient evidence
        if self.forecast_status != ForecastStatus.READY.value or not self.scenarios:
            reason = (
                "Forecast unavailable: insufficient prediction evidence (no active forwardable taint at timestamp)."
                if not self.active_sources
                else "Forecast unavailable: insufficient prediction evidence (no plausible candidate next hops)."
            )
            return ForecastAwareCounterfactualResult(
                intervention_id=intervention_id,
                intervention_type=candidate.intervention_type,
                target_account_id=candidate.target_account_id,
                target_event_id=candidate.target_event_id,
                simulation_timestamp=simulation_timestamp,
                modeled_tainted_capital_intercepted=0,
                modeled_legitimate_capital_affected=0,
                remaining_downstream_taint=0,
                number_of_affected_edges=0,
                number_of_affected_accounts=0,
                provenance_coverage=1.0,
                provenance_confidence=0.0,
                source_interception_details=(),
                explanation=reason,
                blocked_event_ids=(),
                affected_account_ids=(),
                forecast_status=self.forecast_status,
                futures_evaluated_count=0,
                forecast_horizon=0,
                prediction_probabilities=(),
                forecast_confidence=None,
                expected_illicit_interception=0,
                worst_case_illicit_interception=0,
                best_case_illicit_interception=0,
                expected_legitimate_impact=0,
                worst_case_legitimate_impact=0,
                best_case_legitimate_impact=0,
                expected_affected_accounts=0,
                expected_affected_edges=0,
                constraint_satisfaction_probability=0.0,
                per_future_details=(),
            )

        # Simulate candidate across each plausible future
        scenario_evaluations: list[ScenarioEvaluationDetail] = []
        for scenario in self.scenarios:
            simulator = self._simulators[scenario.scenario_id]
            res = simulator.simulate(candidate, simulation_timestamp)
            scenario_evaluations.append(
                ScenarioEvaluationDetail(
                    scenario_id=scenario.scenario_id,
                    scenario_weight=scenario.normalized_weight,
                    path_probability=scenario.cumulative_probability,
                    path_account_ids=scenario.path.accounts_sequence,
                    counterfactual_result=res,
                    is_feasible=True,  # raw simulation outcome
                )
            )

        # Aggregate probability-weighted metrics using exact Decimal arithmetic
        dec_expected_intercepted = sum(
            Decimal(str(detail.scenario_weight))
            * Decimal(detail.counterfactual_result.modeled_tainted_capital_intercepted)
            for detail in scenario_evaluations
        )
        expected_intercepted = int(
            dec_expected_intercepted.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        worst_case_intercepted = min(
            detail.counterfactual_result.modeled_tainted_capital_intercepted
            for detail in scenario_evaluations
        )
        best_case_intercepted = max(
            detail.counterfactual_result.modeled_tainted_capital_intercepted
            for detail in scenario_evaluations
        )

        dec_expected_collateral = sum(
            Decimal(str(detail.scenario_weight))
            * Decimal(detail.counterfactual_result.modeled_legitimate_capital_affected)
            for detail in scenario_evaluations
        )
        expected_collateral = int(
            dec_expected_collateral.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        worst_case_collateral = max(
            detail.counterfactual_result.modeled_legitimate_capital_affected
            for detail in scenario_evaluations
        )
        best_case_collateral = min(
            detail.counterfactual_result.modeled_legitimate_capital_affected
            for detail in scenario_evaluations
        )

        dec_expected_remaining = sum(
            Decimal(str(detail.scenario_weight))
            * Decimal(detail.counterfactual_result.remaining_downstream_taint)
            for detail in scenario_evaluations
        )
        expected_remaining = int(
            dec_expected_remaining.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

        dec_expected_accounts = sum(
            Decimal(str(detail.scenario_weight))
            * Decimal(detail.counterfactual_result.number_of_affected_accounts)
            for detail in scenario_evaluations
        )
        expected_accounts = int(
            dec_expected_accounts.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

        dec_expected_edges = sum(
            Decimal(str(detail.scenario_weight))
            * Decimal(detail.counterfactual_result.number_of_affected_edges)
            for detail in scenario_evaluations
        )
        expected_edges = int(
            dec_expected_edges.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

        min_confidence = min(
            detail.counterfactual_result.provenance_confidence
            for detail in scenario_evaluations
        )
        avg_coverage = float(
            sum(
                detail.scenario_weight
                * detail.counterfactual_result.provenance_coverage
                for detail in scenario_evaluations
            )
        )

        # Fraction of futures where candidate achieved non-zero recovery
        effective_probability = float(
            sum(
                detail.scenario_weight
                for detail in scenario_evaluations
                if detail.counterfactual_result.modeled_tainted_capital_intercepted > 0
            )
        )

        # Aggregate blocked events and affected accounts
        all_blocked_events = sorted(
            set(
                eid
                for detail in scenario_evaluations
                for eid in detail.counterfactual_result.blocked_event_ids
            )
        )
        all_affected_accounts = sorted(
            set(
                aid
                for detail in scenario_evaluations
                for aid in detail.counterfactual_result.affected_account_ids
            )
        )

        # Probability-weighted source details
        source_totals: dict[tuple[str, str], list[tuple[float, int, int]]] = defaultdict(list)
        for detail in scenario_evaluations:
            w = detail.scenario_weight
            for sd in detail.counterfactual_result.source_interception_details:
                source_totals[(sd.source_id, sd.source_case_id)].append(
                    (w, sd.intercepted_amount_minor_units, sd.residual_amount_minor_units)
                )

        weighted_source_details: list[SourceInterceptionDetail] = []
        for (sid, scase), entries in sorted(source_totals.items()):
            w_int = int(round(sum(w * intercept for w, intercept, _ in entries)))
            w_res = int(round(sum(w * resid for w, _, resid in entries)))
            weighted_source_details.append(
                SourceInterceptionDetail(
                    source_id=sid,
                    source_case_id=scase,
                    intercepted_amount_minor_units=w_int,
                    residual_amount_minor_units=w_res,
                )
            )

        target = candidate.target_account_id or candidate.target_event_id or ""
        explanation = (
            f"Forecast-aware {candidate.intervention_type.value} on {target} "
            f"across {len(self.scenarios)} plausible futures: "
            f"expected recovery {expected_intercepted} paise (worst-case {worst_case_intercepted}), "
            f"expected legitimate impact {expected_collateral} paise (worst-case {worst_case_collateral}), "
            f"effectiveness probability {effective_probability:.1%}."
        )

        return ForecastAwareCounterfactualResult(
            intervention_id=intervention_id,
            intervention_type=candidate.intervention_type,
            target_account_id=candidate.target_account_id,
            target_event_id=candidate.target_event_id,
            simulation_timestamp=simulation_timestamp,
            modeled_tainted_capital_intercepted=expected_intercepted,
            modeled_legitimate_capital_affected=worst_case_collateral,  # conservative collateral bounding
            remaining_downstream_taint=expected_remaining,
            number_of_affected_edges=expected_edges,
            number_of_affected_accounts=expected_accounts,
            provenance_coverage=avg_coverage,
            provenance_confidence=min_confidence,
            source_interception_details=tuple(weighted_source_details),
            explanation=explanation,
            blocked_event_ids=tuple(all_blocked_events),
            affected_account_ids=tuple(all_affected_accounts),
            forecast_status=self.forecast_status,
            futures_evaluated_count=len(self.scenarios),
            forecast_horizon=max(len(s.path.hops) for s in self.scenarios) if self.scenarios else 0,
            prediction_probabilities=tuple(s.cumulative_probability for s in self.scenarios),
            forecast_confidence=min_confidence,
            expected_illicit_interception=expected_intercepted,
            worst_case_illicit_interception=worst_case_intercepted,
            best_case_illicit_interception=best_case_intercepted,
            expected_legitimate_impact=expected_collateral,
            worst_case_legitimate_impact=worst_case_collateral,
            best_case_legitimate_impact=best_case_collateral,
            expected_affected_accounts=expected_accounts,
            expected_affected_edges=expected_edges,
            constraint_satisfaction_probability=effective_probability,
            per_future_details=tuple(scenario_evaluations),
        )
