import type {
  InvestigationAnalysisResponse,
  StageExecutionStatus,
  CandidateRecommendation,
} from "../../types/index.ts";
import { formatMinorUnits } from "../currency.ts";

export interface StageBadgeConfig {
  label: string;
  variant: "success" | "warning" | "danger" | "neutral" | "info";
  description: string;
}

export function getStageBadge(status: StageExecutionStatus): StageBadgeConfig {
  switch (status) {
    case "completed":
    case "available":
      return {
        label: "Available",
        variant: "success",
        description: "Stage executed successfully with valid output.",
      };
    case "insufficient_evidence":
      return {
        label: "Insufficient Evidence",
        variant: "warning",
        description: "Stage evaluated, but current data is insufficient to produce future projections.",
      };
    case "infeasible":
      return {
        label: "Policy Infeasible",
        variant: "warning",
        description: "No candidate interventions met strict policy constraint limits.",
      };
    case "unavailable":
      return {
        label: "Unavailable",
        variant: "neutral",
        description: "Stage artifact or required input not configured. No values fabricated.",
      };
    case "failed":
      return {
        label: "Failed",
        variant: "danger",
        description: "Stage execution encountered an internal subsystem error.",
      };
    case "skipped":
      return {
        label: "Skipped",
        variant: "neutral",
        description: "Stage was omitted per configuration.",
      };
    default:
      return {
        label: status,
        variant: "neutral",
        description: "Unknown stage status.",
      };
  }
}

export function isAnalysisStale(
  analysis: InvestigationAnalysisResponse | null,
  currentDecisionTime: string
): boolean {
  if (!analysis) return false;
  const analysisTime = new Date(analysis.simulation_timestamp).getTime();
  const currentTime = new Date(currentDecisionTime).getTime();
  return analysisTime !== currentTime;
}

export function summarizeRecommendationTradeOff(
  candidate: CandidateRecommendation
): string {
  const intercepted = formatMinorUnits(candidate.modeled_tainted_capital_intercepted);
  const collateral = formatMinorUnits(candidate.modeled_legitimate_capital_affected);

  if (candidate.modeled_legitimate_capital_affected === 0) {
    return `Intercepts ${intercepted} illicit proceeds with zero legitimate collateral disruption.`;
  }

  const ratio = (
    candidate.modeled_tainted_capital_intercepted /
    (candidate.modeled_legitimate_capital_affected || 1)
  ).toFixed(1);

  return `Recovers ${intercepted} with ${collateral} collateral affected (${ratio}x efficiency).`;
}

export function formatInterventionExplanation(
  candidate: CandidateRecommendation,
  decisionTimestamp?: string
): string {
  const intercepted = formatMinorUnits(candidate.modeled_tainted_capital_intercepted);
  const collateral = formatMinorUnits(candidate.modeled_legitimate_capital_affected);
  const targetLabel = candidate.target_event_id
    ? `transfer ${candidate.target_event_id}`
    : candidate.target_account_id
    ? `account ${candidate.target_account_id}`
    : `intervention ${candidate.intervention_id}`;

  const timeNotice = decisionTimestamp
    ? ` evaluated at decision time ${decisionTimestamp.slice(11, 19)} UTC`
    : "";

  return `Modelled intervention at ${targetLabel}${timeNotice} could intercept ${intercepted} of attributed tainted funds while affecting an estimated ${collateral} of legitimate funds.`;
}

