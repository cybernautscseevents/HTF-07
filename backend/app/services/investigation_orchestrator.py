"""Investigation Orchestration Service.

Connects the AEGIS-Flow analytical subsystems:
1. Graph ingestion and isolation
2. Deterministic taint propagation
3. Supervised mule risk classification and feature extraction
4. Next-hop predictive ranking
5. Forecast-aware future trajectory generation
6. Temporal min-cut chokepoint search
7. Counterfactual simulation and Pareto intervention optimization
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from backend.app.api.schemas.analysis import (
    CandidateRecommendation,
    ChokepointReport,
    EvaluatedCandidateSummary,
    ForecastReport,
    GraphSummary,
    InvestigationAnalysisRequest,
    InvestigationAnalysisResponse,
    StageExecutionStatus,
    StageReport,
    TaintSummary,
)
from backend.app.chokepoint.candidates import find_temporal_chokepoint
from backend.app.chokepoint.models import ChokepointStatus
from backend.app.counterfactual.candidates import generate_candidates
from backend.app.counterfactual.models import InterventionCandidate, InterventionType
from backend.app.counterfactual.simulator import CounterfactualSimulator
from backend.app.forecast.candidates import generate_forecast_candidates
from backend.app.forecast.evaluator import ForecastAwareCounterfactualEvaluator
from backend.app.forecast.generator import ForecastGeneratorConfig
from backend.app.graph.temporal_graph import TemporalGraph
from backend.app.ml.next_hop import NextHopPredictor
from backend.app.ml.risk_model import MuleRiskModel
from backend.app.optimization.models import (
    OptimizationConstraints,
    candidate_sort_key,
)
from backend.app.optimization.optimizer import (
    MultiObjectiveInterventionOptimizer,
    ObservedFutureCounterfactualEvaluator,
)
from backend.app.repositories.base import CaseRepository, EventRepository
from backend.app.services.case_graph_registry import CaseGraphRegistry
from backend.app.taint.engine import TaintEngine
from backend.app.taint.models import TaintResult, TaintSeed
from contracts.account import AccountReference
from contracts.transaction import TransactionEvent


class CaseNotFoundError(Exception):
    """Raised when the requested case ID does not exist."""


class EmptyCaseError(Exception):
    """Raised when the case contains zero transaction events."""


class InvestigationOrchestrator:
    """Coordinates end-to-end fraud investigation analysis across AEGIS-Flow subsystems."""

    def __init__(
        self,
        case_repo: CaseRepository,
        event_repo: EventRepository,
        graph_registry: CaseGraphRegistry,
        risk_model: MuleRiskModel | None = None,
        next_hop_predictor: NextHopPredictor | None = None,
        model_artifact_dir: Path | None = None,
    ) -> None:
        self._case_repo = case_repo
        self._event_repo = event_repo
        self._graph_registry = graph_registry
        self._risk_model = risk_model
        self._next_hop_predictor = next_hop_predictor
        self._artifact_dir = model_artifact_dir or (
            Path(__file__).resolve().parents[2] / "models" / "artefacts"
        )

        # Attempt lazy-loading of ML models if not injected
        self._try_load_models()

    def _try_load_models(self) -> None:
        """Attempt to load trained models from the artifact directory if available."""
        if self._risk_model is None:
            risk_path = self._artifact_dir / "mule_risk_model.joblib"
            if risk_path.exists():
                try:
                    self._risk_model = MuleRiskModel.load(risk_path)
                except Exception:
                    self._risk_model = None

        if self._next_hop_predictor is None:
            nh_path = self._artifact_dir / "next_hop_predictor.joblib"
            if nh_path.exists():
                try:
                    self._next_hop_predictor = NextHopPredictor.load(nh_path)
                except Exception:
                    self._next_hop_predictor = None

    async def analyze(
        self,
        case_id: str,
        request: InvestigationAnalysisRequest,
    ) -> InvestigationAnalysisResponse:
        """Execute end-to-end investigation sequence for case_id."""
        analysis_timestamp = datetime.now(timezone.utc)

        # ── 1. Load case and validate existence ──────────────────────────────
        case = await self._case_repo.get(case_id)
        if case is None:
            raise CaseNotFoundError(f"Case '{case_id}' not found.")

        # ── 2. Load case events and validate non-empty ───────────────────────
        events = await self._event_repo.get_by_case_id(case_id)
        if not events:
            raise EmptyCaseError(f"Case '{case_id}' contains no transaction events.")

        # ── 3. Validate simulation timestamp and taint seeds ─────────────────
        if request.simulation_timestamp.tzinfo is None:
            raise ValueError("simulation_timestamp must be timezone-aware.")

        case_tx_map = {e.transaction_id: e for e in events}
        for seed_input in request.taint_seeds:
            if seed_input.transaction_id not in case_tx_map:
                raise ValueError(
                    f"Seed transaction '{seed_input.transaction_id}' does not belong to case '{case_id}'."
                )
            if seed_input.tainted_amount_minor_units <= 0:
                raise ValueError("Taint seed amount must be greater than zero.")

        stages: dict[str, StageReport] = {}

        # ── 4. Graph construction & isolation ────────────────────────────────
        # Build an isolated TemporalGraph instance strictly for this investigation run
        graph = TemporalGraph()
        for event in events:
            graph.add_event(event)

        stages["graph_construction"] = StageReport(
            status=StageExecutionStatus.COMPLETED,
            message=f"Constructed isolated case graph with {graph.node_count} accounts and {graph.edge_count} events.",
            details={"node_count": graph.node_count, "edge_count": graph.edge_count},
        )

        # ── 5. Deterministic Taint Propagation ───────────────────────────────
        taint_seeds = [
            TaintSeed(
                case_id=case_id,
                transaction_id=s.transaction_id,
                tainted_amount_minor_units=s.tainted_amount_minor_units,
            )
            for s in request.taint_seeds
        ]
        taint_engine = TaintEngine()
        baseline_taint: TaintResult = taint_engine.run(graph, taint_seeds)

        # Build isolated historical graph <= simulation_timestamp
        historical_graph = TemporalGraph()
        for edge in graph.events_between(end=request.simulation_timestamp, active_only=True):
            historical_graph.add_event(
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

        active_historical_tx_ids = {
            edge.transaction_id
            for edge in historical_graph.events_between(active_only=True)
        }
        active_historical_seeds = tuple(
            seed for seed in taint_seeds
            if seed.transaction_id in active_historical_tx_ids
        )
        historical_taint = (
            taint_engine.run(historical_graph, list(active_historical_seeds))
            if active_historical_seeds
            else taint_engine.run(historical_graph, [])
        )

        tainted_accounts_at_t = [
            b.account_id for b in historical_taint.current_tainted_accounts()
            if b.tainted_balance_minor_units > 0
        ]
        total_propagated_at_t = sum(
            alloc.tainted_amount_minor_units for alloc in historical_taint.allocations
        )

        stages["taint_propagation"] = StageReport(
            status=StageExecutionStatus.COMPLETED,
            message=f"Propagated {len(active_historical_seeds)} seeds over {len(historical_taint.allocations)} historical edges.",
            details={
                "allocated_edges": len(historical_taint.allocations),
                "tainted_accounts_count": len(tainted_accounts_at_t),
                "shortfall_count": len(historical_taint.shortfalls),
            },
        )

        # ── 6. ML Risk Intelligence & Next-Hop Predictions ───────────────────
        target_eval_accounts = tainted_accounts_at_t if tainted_accounts_at_t else sorted(historical_graph.accounts)

        risk_predictions_data: list[dict[str, Any]] = []
        if self._risk_model is not None:
            try:
                for acct in target_eval_accounts:
                    pred = self._risk_model.predict_risk(
                        graph=historical_graph,
                        account_id=acct,
                        as_of_time=request.simulation_timestamp,
                    )
                    risk_predictions_data.append(pred.model_dump(mode="json"))
                stages["risk_assessment"] = StageReport(
                    status=StageExecutionStatus.AVAILABLE,
                    details={"assessed_accounts_count": len(risk_predictions_data)},
                )
            except Exception as exc:
                stages["risk_assessment"] = StageReport(
                    status=StageExecutionStatus.FAILED,
                    message=f"Risk model evaluation failed: {exc}",
                )
        else:
            stages["risk_assessment"] = StageReport(
                status=StageExecutionStatus.UNAVAILABLE,
                message="Mule risk model artifact unavailable. No risk scores fabricated.",
            )

        next_hop_predictions_data: list[dict[str, Any]] = []
        # NextHopPredictor can run with fallback heuristic even if unfitted
        predictor = self._next_hop_predictor or NextHopPredictor()
        try:
            for acct in target_eval_accounts:
                nh_pred = predictor.predict_next_hop(
                    graph=historical_graph,
                    source_account_id=acct,
                    as_of_time=request.simulation_timestamp,
                )
                if nh_pred.candidates:
                    next_hop_predictions_data.append({
                        "source_account_id": nh_pred.source_account_id,
                        "top_1_account_id": nh_pred.top_1_account_id,
                        "model_version": nh_pred.model_version,
                        "prediction_timestamp": nh_pred.prediction_timestamp.isoformat(),
                        "candidates": [
                            {
                                "account_id": c.account_id,
                                "probability": c.predicted_probability,
                                "rank": c.rank,
                            }
                            for c in nh_pred.candidates
                        ],
                    })
            if next_hop_predictions_data:
                stages["next_hop_prediction"] = StageReport(
                    status=StageExecutionStatus.AVAILABLE,
                    details={"predicted_sources_count": len(next_hop_predictions_data)},
                )
            else:
                stages["next_hop_prediction"] = StageReport(
                    status=StageExecutionStatus.INSUFFICIENT_EVIDENCE,
                    message="No next-hop candidate destinations observed up to simulation_timestamp.",
                )
        except Exception as exc:
            stages["next_hop_prediction"] = StageReport(
                status=StageExecutionStatus.FAILED,
                message=f"Next-hop prediction failed: {exc}",
            )

        # ── 7. Forecast-Aware Scenario Evaluation ────────────────────────────
        forecast_report = ForecastReport(
            status="unavailable",
            paths_generated_count=0,
            scenarios_evaluated_count=0,
        )
        forecast_candidates: list[InterventionCandidate] = []

        if tainted_accounts_at_t:
            fc_cfg = (
                ForecastGeneratorConfig(
                    top_k=request.forecast_config.top_k,
                    max_depth=request.forecast_config.max_depth,
                    hop_delay_seconds=request.forecast_config.hop_delay_seconds,
                )
                if request.forecast_config
                else ForecastGeneratorConfig()
            )
            try:
                fc_evaluator = ForecastAwareCounterfactualEvaluator(
                    graph=graph,
                    taint_seeds=taint_seeds,
                    simulation_timestamp=request.simulation_timestamp,
                    predictor=predictor,
                    config=fc_cfg,
                )
                if len(fc_evaluator.paths) > 0:
                    forecast_report = ForecastReport(
                        status="available",
                        paths_generated_count=len(fc_evaluator.paths),
                        scenarios_evaluated_count=len(fc_evaluator.scenarios),
                    )
                    stages["forecast_simulation"] = StageReport(
                        status=StageExecutionStatus.AVAILABLE,
                        details={
                            "paths_generated": len(fc_evaluator.paths),
                            "scenarios_evaluated": len(fc_evaluator.scenarios),
                        },
                    )
                    forecast_candidates = generate_forecast_candidates(
                        graph=graph,
                        taint_at_t=fc_evaluator.taint_at_t,
                        simulation_timestamp=request.simulation_timestamp,
                        scenarios=fc_evaluator.scenarios,
                        include_edge_holds=False,
                    )
                else:
                    forecast_report = ForecastReport(
                        status="insufficient_evidence",
                        paths_generated_count=0,
                        scenarios_evaluated_count=0,
                    )
                    stages["forecast_simulation"] = StageReport(
                        status=StageExecutionStatus.INSUFFICIENT_EVIDENCE,
                        message="No plausible future trajectories identified within forecast horizon.",
                    )
            except Exception as exc:
                forecast_report = ForecastReport(
                    status="failed",
                    paths_generated_count=0,
                    scenarios_evaluated_count=0,
                )
                stages["forecast_simulation"] = StageReport(
                    status=StageExecutionStatus.FAILED,
                    message=f"Forecast generation failed: {exc}",
                )
        else:
            stages["forecast_simulation"] = StageReport(
                status=StageExecutionStatus.UNAVAILABLE,
                message="No active tainted sources available at simulation_timestamp.",
            )

        # ── 8. Temporal Min-Cut Chokepoint Search ────────────────────────────
        chokepoint_report: ChokepointReport | None = None
        chokepoint_candidates: list[InterventionCandidate] = []

        if request.sink_account_ids:
            # Determine fraud sources: explicitly given or seed receivers
            if request.source_account_ids:
                source_accounts = request.source_account_ids
            else:
                source_accounts = list(
                    {case_tx_map[s.transaction_id].receiver.account_id for s in request.taint_seeds}
                )

            overlap = set(source_accounts) & set(request.sink_account_ids)
            if overlap:
                raise ValueError(
                    f"source_account_ids and sink_account_ids cannot overlap: {sorted(overlap)}"
                )

            simulator = CounterfactualSimulator(graph, baseline_taint)
            cp_result = find_temporal_chokepoint(
                graph=graph,
                source_account_ids=source_accounts,
                sink_account_ids=request.sink_account_ids,
                simulation_timestamp=request.simulation_timestamp,
                eligible_event_ids=request.eligible_event_ids,
                simulator=simulator,
            )

            chokepoint_report = ChokepointReport(
                status=cp_result.status.value,
                cut_size=cp_result.cut_size,
                cut_event_ids=list(cp_result.cut_event_ids),
                total_encoded_cut_cost=cp_result.total_encoded_cut_cost,
                total_estimated_collateral_minor_units=cp_result.total_estimated_legitimate_collateral_minor_units,
                is_cut_verified=cp_result.is_cut_verified,
                explanation_summary=cp_result.explanation.summary,
            )
            chokepoint_candidates = list(cp_result.candidates)

            stages["chokepoint_search"] = StageReport(
                status=(
                    StageExecutionStatus.AVAILABLE
                    if cp_result.is_feasible
                    else (
                        StageExecutionStatus.COMPLETED
                        if cp_result.status == ChokepointStatus.NO_PATH_EXISTS
                        else StageExecutionStatus.INFEASIBLE
                    )
                ),
                details={
                    "chokepoint_status": cp_result.status.value,
                    "cut_size": cp_result.cut_size,
                    "is_cut_verified": cp_result.is_cut_verified,
                },
            )
        else:
            stages["chokepoint_search"] = StageReport(
                status=StageExecutionStatus.UNAVAILABLE,
                message="No sink_account_ids specified for chokepoint search.",
            )

        # ── 9. Candidate Generation & Pareto Optimization ────────────────────
        base_candidates = generate_candidates(
            graph=graph,
            baseline_result=baseline_taint,
            simulation_timestamp=request.simulation_timestamp,
        )

        all_candidates = base_candidates + chokepoint_candidates + forecast_candidates
        # Deduplicate deterministically
        candidate_pool = sorted(set(all_candidates), key=candidate_sort_key)

        # Filter by requested eligible_event_ids if provided
        if request.eligible_event_ids is not None:
            allowed_events = set(request.eligible_event_ids)
            candidate_pool = [
                c for c in candidate_pool
                if c.intervention_type == InterventionType.ACCOUNT_HOLD
                or (c.target_event_id is not None and c.target_event_id in allowed_events)
            ]

        # Prevent historical events from ever being candidates
        valid_future_candidates: list[InterventionCandidate] = []
        for cand in candidate_pool:
            if cand.intervention_type == InterventionType.EDGE_HOLD:
                assert cand.target_event_id is not None
                try:
                    edge_data = graph.get_edge_by_event(cand.target_event_id)
                except KeyError:
                    continue  # not an observed graph edge
                if edge_data.occurred_at <= request.simulation_timestamp:
                    continue  # historical event cannot be held
            valid_future_candidates.append(cand)

        # Evaluate candidates via CounterfactualSimulator and MultiObjectiveInterventionOptimizer
        simulator = CounterfactualSimulator(graph, baseline_taint)
        constraints = (
            OptimizationConstraints(
                minimum_required_illicit_recovery=request.constraints.minimum_required_illicit_recovery,
                maximum_legitimate_capital_affected=request.constraints.maximum_legitimate_capital_affected,
                maximum_affected_accounts=request.constraints.maximum_affected_accounts,
                maximum_affected_edges=request.constraints.maximum_affected_edges,
                maximum_interventions=request.constraints.maximum_interventions,
                minimum_provenance_confidence=request.constraints.minimum_provenance_confidence,
            )
            if request.constraints
            else OptimizationConstraints()
        )

        optimizer = MultiObjectiveInterventionOptimizer(
            evaluator=ObservedFutureCounterfactualEvaluator(simulator)
        )
        opt_output = optimizer.optimize(
            candidates=valid_future_candidates,
            simulation_timestamp=request.simulation_timestamp,
            constraints=constraints,
        )

        selected_rec: CandidateRecommendation | None = None
        if opt_output.selected_evaluation is not None:
            sel = opt_output.selected_evaluation
            selected_rec = CandidateRecommendation(
                intervention_id=sel.intervention_id,
                intervention_type=sel.candidate.intervention_type.value,
                target_account_id=sel.candidate.target_account_id,
                target_event_id=sel.candidate.target_event_id,
                modeled_tainted_capital_intercepted=sel.result.modeled_tainted_capital_intercepted,
                modeled_legitimate_capital_affected=sel.result.modeled_legitimate_capital_affected,
                remaining_downstream_taint=sel.result.remaining_downstream_taint,
                number_of_affected_edges=sel.result.number_of_affected_edges,
                number_of_affected_accounts=sel.result.number_of_affected_accounts,
                provenance_confidence=sel.result.provenance_confidence,
                recovery_efficiency=str(sel.recovery_efficiency),
                policy_feasible=sel.feasible,
                explanation=sel.result.explanation,
            )
            stages["intervention_optimization"] = StageReport(
                status=StageExecutionStatus.AVAILABLE,
                details={
                    "total_candidates": len(opt_output.evaluations),
                    "feasible_candidates": len(opt_output.feasible_evaluations),
                    "selected_intervention_id": sel.intervention_id,
                },
            )
        else:
            stages["intervention_optimization"] = StageReport(
                status=(
                    StageExecutionStatus.INFEASIBLE
                    if opt_output.evaluations
                    else StageExecutionStatus.UNAVAILABLE
                ),
                message=(
                    "No candidates met hard policy constraints."
                    if opt_output.evaluations
                    else "No intervention candidates generated for future evaluation."
                ),
            )

        evaluated_summary = EvaluatedCandidateSummary(
            total_candidates_count=len(opt_output.evaluations),
            feasible_candidates_count=len(opt_output.feasible_evaluations),
            infeasible_candidates_count=len(opt_output.infeasible_evaluations),
            pareto_frontier_size=opt_output.pareto_frontier.size,
        )

        # ── 10. Assemble structured investigation response ───────────────────
        overall_status = "completed"
        if any(
            s.status in (StageExecutionStatus.FAILED, StageExecutionStatus.UNAVAILABLE)
            for s in stages.values()
        ):
            overall_status = "partial"

        warnings_and_limitations = [
            "DECISION SUPPORT ONLY: This analysis is an investigator-facing decision support output and does NOT constitute an authorized bank instruction, legal freeze, or payment block.",
            "AEGIS-Flow never automatically submits hold instructions to payment gateways or partner banks.",
            "No future ground-truth data after simulation_timestamp was accessed or used to select intervention candidates.",
            "Forecast trajectories are simulation-only hypotheses and are NEVER persisted as real financial transactions.",
            "Additive collateral approximation: single-edge counterfactual collateral estimates sum independently; joint non-linear interaction effects may differ if multiple holds occur.",
            "Settlement ordering abstraction: events occurring at identical timestamps are treated as causally disconnected per the MVP causality rule.",
        ]

        return InvestigationAnalysisResponse(
            case_id=case_id,
            simulation_timestamp=request.simulation_timestamp,
            analysis_timestamp=analysis_timestamp,
            overall_status=overall_status,
            stages=stages,
            graph_summary=GraphSummary(
                node_count=graph.node_count,
                edge_count=graph.edge_count,
                account_ids=sorted(graph.accounts),
            ),
            taint_summary=TaintSummary(
                seed_count=len(active_historical_seeds),
                allocated_edge_count=len(historical_taint.allocations),
                current_tainted_account_count=len(tainted_accounts_at_t),
                total_propagated_volume_minor_units=total_propagated_at_t,
                shortfall_count=len(historical_taint.shortfalls),
                current_tainted_accounts=tainted_accounts_at_t,
            ),
            risk_predictions=risk_predictions_data,
            next_hop_predictions=next_hop_predictions_data,
            forecast_report=forecast_report,
            chokepoint_report=chokepoint_report,
            evaluated_candidates=evaluated_summary,
            selected_recommendation=selected_rec,
            warnings_and_limitations=warnings_and_limitations,
        )
