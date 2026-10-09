"use client";

import React, { useState } from "react";
import {
  ShieldCheck,
  Scale,
  ChevronDown,
  ChevronUp,
  FileText,
} from "lucide-react";
import { CandidateRecommendation } from "@/types";
import { formatMinorUnits, formatPaise, formatEfficiency } from "@/lib/currency";
import { StatusBadge } from "@/components/ui/StatusBadge";
import {
  summarizeRecommendationTradeOff,
  formatInterventionExplanation,
} from "@/lib/mappers/analysisMapper";

interface RecommendationCardProps {
  recommendation: CandidateRecommendation | null;
  decisionTimestamp?: string;
}

export function RecommendationCard({
  recommendation,
  decisionTimestamp,
}: RecommendationCardProps) {
  const [showAuditDetails, setShowAuditDetails] = useState<boolean>(false);

  if (!recommendation) {
    return (
      <div className="rounded-2xl border border-[#23233c] bg-[#121222] p-6 text-xs text-slate-400 font-sans text-center">
        No candidate intervention met policy feasibility constraints at decision cutoff.
      </div>
    );
  }

  const tradeOffSummary = summarizeRecommendationTradeOff(recommendation);
  const plainLanguageExplanation = formatInterventionExplanation(
    recommendation,
    decisionTimestamp
  );

  return (
    <div className="rounded-2xl border border-[#23233c] bg-[#121222] p-5 lg:p-6 space-y-4 shadow-md font-sans">
      {/* Top Banner */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3.5 border-b border-[#23233c]">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#6666ff]/15 text-[#b0baff] border border-[#6666ff]/30">
            <ShieldCheck className="h-5 w-5 text-[#6666ff]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold text-white font-sans">
                Recommended intervention
              </span>
              <span className="text-[11px] font-sans px-2.5 py-0.5 rounded-full bg-[#17172b] border border-[#23233c] text-[#b0baff]">
                Pareto optimal
              </span>
            </div>
            <p className="text-xs text-slate-400 font-sans mt-0.5">
              Targeted hold balancing maximum fraud containment against zero or minimal legitimate customer disruption
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <StatusBadge
            label={recommendation.policy_feasible ? "Policy feasible" : "Infeasible"}
            variant={recommendation.policy_feasible ? "success" : "danger"}
            size="sm"
          />
          <span className="text-xs font-mono px-2.5 py-1 rounded-lg bg-[#17172b] text-slate-200 border border-[#23233c]">
            {recommendation.intervention_type === "edge_hold" ? "Transfer hold" : "Account hold"}
          </span>
        </div>
      </div>

      {/* Investigator Plain-Language Explanation */}
      <div className="p-4 rounded-xl bg-[#17172b] border border-[#23233c] text-xs text-slate-200 leading-relaxed space-y-2">
        <p className="font-medium text-slate-100 text-sm">
          {plainLanguageExplanation}
        </p>
        <div className="text-xs text-slate-400 pt-2 border-t border-[#23233c] flex flex-wrap gap-x-6 gap-y-1">
          <span>
            <strong>Target:</strong>{" "}
            <span className="font-mono text-slate-200">
              {recommendation.target_event_id || recommendation.target_account_id}
            </span>
          </span>
          <span>
            <strong>Why preferred:</strong> Optimal Pareto efficiency score ({formatEfficiency(recommendation.recovery_efficiency)})
          </span>
        </div>
      </div>

      {/* 4 Core Quantitative Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="p-4 rounded-xl bg-[#0c0c16]/80 border border-[#23233c]">
          <div className="text-[11px] text-slate-400 font-sans">
            Illicit proceeds intercepted
          </div>
          <div className="text-lg font-bold text-[#b9f0d7] font-mono mt-1">
            {formatMinorUnits(recommendation.modeled_tainted_capital_intercepted)}
          </div>
          <div className="text-[11px] text-slate-500 font-mono mt-0.5">
            {formatPaise(recommendation.modeled_tainted_capital_intercepted)}
          </div>
        </div>

        <div className="p-4 rounded-xl bg-[#0c0c16]/80 border border-[#23233c]">
          <div className="text-[11px] text-slate-400 font-sans">
            Legitimate capital affected
          </div>
          <div className={`text-lg font-bold font-mono mt-1 ${recommendation.modeled_legitimate_capital_affected > 0 ? "text-[#e5a84b]" : "text-slate-400"}`}>
            {formatMinorUnits(recommendation.modeled_legitimate_capital_affected)}
          </div>
          <div className="text-[11px] text-slate-500 font-sans mt-0.5">
            {recommendation.modeled_legitimate_capital_affected === 0 ? "Zero customer collateral" : "Customer disruption"}
          </div>
        </div>

        <div className="p-4 rounded-xl bg-[#0c0c16]/80 border border-[#23233c]">
          <div className="text-[11px] text-slate-400 font-sans">
            Attribution confidence
          </div>
          <div className="text-lg font-bold text-[#c9e8ff] font-mono mt-1">
            {(recommendation.provenance_confidence * 100).toFixed(0)}%
          </div>
          <div className="text-[11px] text-slate-400 font-sans mt-0.5">
            Efficiency: <span className="font-mono text-slate-200">{formatEfficiency(recommendation.recovery_efficiency)}</span>
          </div>
        </div>

        <div className="p-4 rounded-xl bg-[#0c0c16]/80 border border-[#23233c]">
          <div className="text-[11px] text-slate-400 font-sans">
            Unintercepted downstream
          </div>
          <div className="text-lg font-bold text-slate-300 font-mono mt-1">
            {formatMinorUnits(recommendation.remaining_downstream_taint)}
          </div>
          <div className="text-[11px] text-slate-500 font-sans mt-0.5">
            Residual taint at risk
          </div>
        </div>
      </div>

      {/* Multi-Future Forecast Robustness (If Available) */}
      {recommendation.expected_illicit_interception != null && (
        <div className="p-4 rounded-xl bg-[#17172b] border border-[#23233c] space-y-2 text-xs">
          <div className="flex items-center gap-2 font-semibold text-[#c9e8ff] font-sans">
            <Scale className="h-4 w-4 text-[#6666ff]" />
            <span>Simulated multi-future robustness</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs pt-1">
            <div className="p-2.5 rounded-lg bg-[#0c0c16]/80 border border-[#23233c]">
              <span className="text-[10px] text-slate-400 block font-sans">Expected recovery</span>
              <strong className="text-[#c9e8ff] text-sm font-mono">
                {formatMinorUnits(recommendation.expected_illicit_interception)}
              </strong>
            </div>
            <div className="p-2.5 rounded-lg bg-[#0c0c16]/80 border border-[#23233c]">
              <span className="text-[10px] text-slate-400 block font-sans">Worst-case recovery</span>
              <strong className="text-[#e5a84b] text-sm font-mono">
                {formatMinorUnits(recommendation.worst_case_illicit_interception || 0)}
              </strong>
            </div>
            <div className="p-2.5 rounded-lg bg-[#0c0c16]/80 border border-[#23233c]">
              <span className="text-[10px] text-slate-400 block font-sans">Expected collateral</span>
              <strong className="text-slate-200 text-sm font-mono">
                {formatMinorUnits(recommendation.expected_legitimate_impact || 0)}
              </strong>
            </div>
            <div className="p-2.5 rounded-lg bg-[#0c0c16]/80 border border-[#23233c]">
              <span className="text-[10px] text-slate-400 block font-sans">Constraint probability</span>
              <strong className="text-[#b9f0d7] text-sm font-mono">
                {((recommendation.constraint_satisfaction_probability || 1) * 100).toFixed(0)}%
              </strong>
            </div>
          </div>
        </div>
      )}

      {/* Trade-Off Summary */}
      <div className="p-3.5 rounded-xl bg-[#17172b] border border-[#23233c] text-xs flex flex-wrap items-center justify-between gap-2 font-sans">
        <div className="flex items-center gap-2 text-slate-400 text-xs">
          <FileText className="h-4 w-4 text-slate-500" />
          <span>Optimization summary:</span>
        </div>
        <span className="font-medium text-[#b9f0d7] text-xs">
          {tradeOffSummary}
        </span>
      </div>

      {/* Expandable Forensic Audit Details */}
      <div className="pt-1">
        <button
          onClick={() => setShowAuditDetails(!showAuditDetails)}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 cursor-pointer font-sans"
        >
          {showAuditDetails ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          <span>{showAuditDetails ? "Hide forensic audit details" : "View forensic audit details (IDs, affected edges, exact metrics)"}</span>
        </button>

        {showAuditDetails && (
          <div className="mt-2.5 p-4 rounded-xl bg-[#0c0c16] border border-[#23233c] text-xs space-y-2.5 text-slate-300 font-sans">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              <div>
                <span className="text-slate-500 font-sans">Intervention ID: </span>
                <span className="text-white font-mono select-all">{recommendation.intervention_id}</span>
              </div>
              <div>
                <span className="text-slate-500 font-sans">Target Entity: </span>
                <span className="text-white font-mono select-all">
                  {recommendation.target_event_id || recommendation.target_account_id || "N/A"}
                </span>
              </div>
              <div>
                <span className="text-slate-500 font-sans">Affected Accounts: </span>
                <span className="text-white font-mono">{recommendation.number_of_affected_accounts}</span>
              </div>
              <div>
                <span className="text-slate-500 font-sans">Affected Edges: </span>
                <span className="text-white font-mono">{recommendation.number_of_affected_edges}</span>
              </div>
              <div>
                <span className="text-slate-500 font-sans">Raw Recovery Efficiency: </span>
                <span className="text-white font-mono">{recommendation.recovery_efficiency}</span>
              </div>
              <div>
                <span className="text-slate-500 font-sans">Pareto Rank: </span>
                <span className="text-white font-mono">{recommendation.pareto_rank || 1}</span>
              </div>
            </div>
            <div className="text-[11px] text-slate-400 pt-2 border-t border-[#23233c] leading-relaxed">
              Operational Notice: Recommendation is provided strictly for compliance and investigator review. Attribution reflects mathematical flow conservation on pooled balances and does not constitute an automated legal freeze or statutory proof of culpability.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
