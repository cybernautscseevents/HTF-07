export type StageExecutionStatus =
  | "available"
  | "unavailable"
  | "insufficient_evidence"
  | "infeasible"
  | "failed"
  | "completed"
  | "skipped";

export interface TaintSeedInput {
  transaction_id: string;
  tainted_amount_minor_units: number;
}

export interface ForecastConfigInput {
  top_k?: number;
  max_depth?: number;
  hop_delay_seconds?: number;
}

export interface OptimizationConstraintsInput {
  minimum_required_illicit_recovery?: number;
  maximum_legitimate_capital_affected?: number | null;
  maximum_affected_accounts?: number | null;
  maximum_affected_edges?: number | null;
  maximum_interventions?: number;
  minimum_provenance_confidence?: number | null;
}

export interface InvestigationAnalysisRequest {
  simulation_timestamp: string;
  taint_seeds: TaintSeedInput[];
  sink_account_ids?: string[] | null;
  source_account_ids?: string[] | null;
  eligible_event_ids?: string[] | null;
  forecast_config?: ForecastConfigInput | null;
  constraints?: OptimizationConstraintsInput | null;
}

export interface StageReport {
  status: StageExecutionStatus;
  message?: string | null;
  details?: Record<string, unknown>;
}

export interface GraphSummary {
  node_count: number;
  edge_count: number;
  account_ids: string[];
}

export interface TaintSummary {
  seed_count: number;
  allocated_edge_count: number;
  current_tainted_account_count: number;
  total_propagated_volume_minor_units: number;
  shortfall_count: number;
  current_tainted_accounts: string[];
}

export interface ChokepointReport {
  status: string;
  cut_size: number;
  cut_event_ids: string[];
  total_encoded_cut_cost: number;
  total_estimated_collateral_minor_units: number;
  is_cut_verified: boolean;
  explanation_summary?: string | null;
}

export interface ForecastHopDetail {
  from_account_id: string;
  to_account_id: string;
  amount_minor_units: number;
  probability: number;
  occurred_at: string;
}

export interface ForecastPathDetail {
  path_id: string;
  source_account_id: string;
  cumulative_probability: number;
  accounts_sequence: string[];
  hops: ForecastHopDetail[];
}

export interface ForecastReport {
  status: string;
  paths_generated_count: number;
  scenarios_evaluated_count: number;
  paths?: ForecastPathDetail[];
}

export interface CandidateRecommendation {
  intervention_id: string;
  intervention_type: "account_hold" | "edge_hold" | string;
  target_account_id?: string | null;
  target_event_id?: string | null;
  modeled_tainted_capital_intercepted: number;
  modeled_legitimate_capital_affected: number;
  remaining_downstream_taint: number;
  number_of_affected_edges: number;
  number_of_affected_accounts: number;
  provenance_confidence: number;
  recovery_efficiency: string;
  policy_feasible: boolean;
  explanation: string;
  expected_illicit_interception?: number | null;
  worst_case_illicit_interception?: number | null;
  expected_legitimate_impact?: number | null;
  worst_case_legitimate_impact?: number | null;
  constraint_satisfaction_probability?: number | null;
  pareto_rank?: number | null;
  dominated_by?: string[];
  constraint_violations?: string[];
}

export interface EvaluatedCandidateSummary {
  total_candidates_count: number;
  feasible_candidates_count: number;
  infeasible_candidates_count: number;
  pareto_frontier_size: number;
}

export interface RiskPrediction {
  account_id: string;
  risk_score: number;
  risk_level: string;
  model_version: string;
  prediction_timestamp: string;
  features_used?: Record<string, unknown>;
  top_risk_factors?: string[];
}

export interface NextHopCandidate {
  account_id: string;
  probability: number;
  rank: number;
}

export interface NextHopPrediction {
  source_account_id: string;
  top_1_account_id: string | null;
  model_version: string;
  prediction_timestamp: string;
  candidates: NextHopCandidate[];
}

export interface InvestigationAnalysisResponse {
  case_id: string;
  simulation_timestamp: string;
  analysis_timestamp: string;
  overall_status: string;
  stages: Record<string, StageReport>;
  graph_summary: GraphSummary;
  taint_summary: TaintSummary;
  risk_predictions: RiskPrediction[];
  next_hop_predictions: NextHopPrediction[];
  forecast_report: ForecastReport;
  chokepoint_report: ChokepointReport | null;
  evaluated_candidates: EvaluatedCandidateSummary;
  selected_recommendation: CandidateRecommendation | null;
  all_candidates?: CandidateRecommendation[];
  competing_candidates?: Array<{ intervention_id: string; reason: string }>;
  warnings_and_limitations: string[];
}
