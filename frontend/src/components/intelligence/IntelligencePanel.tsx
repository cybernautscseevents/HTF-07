"use client";

import React, { useState } from "react";
import { Brain, TrendingUp, ArrowRight, Route, Cpu, Info, ChevronDown, ChevronUp, AlertCircle } from "lucide-react";
import {
  RiskPrediction,
  NextHopPrediction,
  ForecastReport,
  StageReport,
} from "@/types";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatMinorUnits } from "@/lib/currency";

interface IntelligencePanelProps {
  riskPredictions: RiskPrediction[];
  nextHopPredictions: NextHopPrediction[];
  forecastReport: ForecastReport | null;
  riskStage?: StageReport;
  nextHopStage?: StageReport;
  forecastStage?: StageReport;
}

export function IntelligencePanel({
  riskPredictions,
  nextHopPredictions,
  forecastReport,
  riskStage,
  nextHopStage,
  forecastStage,
}: IntelligencePanelProps) {
  const [showTechnicalMath, setShowTechnicalMath] = useState<boolean>(false);

  return (
    <div className="rounded-xl border border-surface-border bg-surface-elevated p-4 lg:p-5 space-y-4 shadow-xl">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-surface-border">
        <div>
          <div className="flex items-center gap-2">
            <Brain className="h-4 w-4 text-brand-periwinkle" />
            <h2 className="text-sm font-semibold text-white tracking-wide">
              Predictions and risk signals
            </h2>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Probabilistic forward simulations to identify likely egress routes ahead of fund transfers.
          </p>
        </div>
        <div className="flex items-center gap-2 font-sans">
          {riskStage && (
            <StatusBadge
              label={`Risk model: ${riskStage.status}`}
              variant={
                riskStage.status === "available"
                  ? "success"
                  : riskStage.status === "unavailable"
                  ? "neutral"
                  : "warning"
              }
              size="sm"
            />
          )}
          {forecastStage && (
            <StatusBadge
              label={`Forecast horizon: ${forecastStage.status}`}
              variant={
                forecastStage.status === "available"
                  ? "success"
                  : forecastStage.status === "insufficient_evidence"
                  ? "warning"
                  : "neutral"
              }
              size="sm"
            />
          )}
        </div>
      </div>

      {/* Methodological Guidance Notice */}
      <div className="p-3.5 rounded-lg bg-surface-raised border border-surface-border text-xs text-slate-300 leading-relaxed flex items-start gap-2.5">
        <TrendingUp className="h-4 w-4 shrink-0 text-brand-periwinkle mt-0.5" />
        <p>
          <strong>Predictive intelligence scope:</strong> Next-hop candidate rankings and path forecasts evaluate plausible egress trajectories based on graph topology. These are <strong>forward-looking simulations</strong> to help position holds proactively, not confirmed or settled transactions.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Section A: Mule Risk Classification */}
        <div className="space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-200 tracking-wide flex items-center gap-1.5">
              <Cpu className="h-3.5 w-3.5 text-brand-periwinkle" />
              <span>Account mule risk classification</span>
            </span>
            <span className="text-[11px] text-slate-400">
              Supervised GBT
            </span>
          </div>

          {riskPredictions.length === 0 ? (
            <div className="p-4 rounded-lg bg-surface-raised border border-surface-border text-xs text-slate-400 text-center space-y-1">
              <div className="text-slate-300 font-medium">Risk model offline or unavailable</div>
              <p className="text-[11px] text-slate-400">
                {riskStage?.message ||
                  "No risk model weights loaded. Risk scores and behavioral explanations are omitted to prevent fabrication."}
              </p>
            </div>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
              {riskPredictions.map((rp) => (
                <div
                  key={rp.account_id}
                  className="p-3 rounded-lg bg-surface-raised border border-surface-border space-y-1.5"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-white font-mono select-all">
                      {rp.account_id}
                    </span>
                    <StatusBadge
                      label={`${rp.risk_level} • ${(rp.risk_score * 100).toFixed(1)}%`}
                      variant={
                        rp.risk_level === "CRITICAL" || rp.risk_level === "HIGH"
                          ? "danger"
                          : "warning"
                      }
                      size="sm"
                    />
                  </div>

                  <div className="flex justify-between text-[11px] text-slate-400 pt-1">
                    <span>Model: {rp.model_version}</span>
                    <span className="font-mono">As of: {rp.prediction_timestamp.slice(11, 19)} UTC</span>
                  </div>

                  {rp.top_risk_factors && rp.top_risk_factors.length > 0 && (
                    <div className="text-[11px] text-slate-300 pt-1.5 border-t border-surface-border">
                      <span className="text-slate-400 font-medium">Observed signals: </span>
                      {rp.top_risk_factors.join(", ")}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Section B: Next-Hop Candidates */}
        <div className="space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-200 tracking-wide flex items-center gap-1.5">
              <Route className="h-3.5 w-3.5 text-brand-periwinkle" />
              <span>Next-hop destination ranking</span>
            </span>
            <span className="text-[11px] text-slate-400">
              Beam search horizon
            </span>
          </div>

          {nextHopPredictions.length === 0 ? (
            <div className="p-4 rounded-lg bg-surface-raised border border-surface-border text-xs text-slate-400 text-center">
              {nextHopStage?.message ||
                "No candidate next-hop destinations observed up to the simulation timestamp."}
            </div>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
              {nextHopPredictions.map((nh) => (
                <div
                  key={nh.source_account_id}
                  className="p-3 rounded-lg bg-surface-raised border border-surface-border space-y-2"
                >
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-300">
                      Origin account:{" "}
                      <strong className="text-white font-mono select-all">
                        {nh.source_account_id}
                      </strong>
                    </span>
                    <span className="text-[11px] text-slate-400">
                      v{nh.model_version}
                    </span>
                  </div>

                  <div className="space-y-1.5 pt-1">
                    {nh.candidates.map((c) => (
                      <div
                        key={c.account_id}
                        className="flex items-center justify-between text-xs p-2 rounded-md bg-surface-card border border-surface-border"
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-slate-500 font-mono text-[11px]">
                            #{c.rank}
                          </span>
                          <span className="text-slate-200 font-mono select-all">{c.account_id}</span>
                        </div>
                        <div className="text-right">
                          <span className="text-brand-columbia font-semibold font-mono">
                            {(c.probability * 100).toFixed(0)}%
                          </span>
                          <span className="text-[10px] text-slate-400 block">
                            candidate share
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Reciprocal 100% Probability Clarification Callout */}
      {nextHopPredictions.some((nh) => nh.candidates.some((c) => c.probability === 1.0)) && (
        <div className="p-3 rounded-lg bg-surface-raised border border-brand-primary/30 flex items-start gap-2.5 text-xs text-slate-300">
          <AlertCircle className="h-4 w-4 text-brand-periwinkle shrink-0 mt-0.5" />
          <div className="space-y-1">
            <span className="font-semibold text-slate-200">
              Understanding the 100% candidate share ranking:
            </span>
            <p className="text-slate-400 text-[11px] leading-relaxed">
              At the current investigation timestamp, each active account has exactly one downstream destination eligible under the beam search exclusion criteria (upstream source accounts are excluded to prevent cycles). Softmax normalization across a single eligible candidate mathematically produces 100%. This indicates <strong>sole eligible candidate share within the candidate pool</strong>, not absolute certainty of a real-world transfer.
            </p>
          </div>
        </div>
      )}

      {/* Section C: Forecast Paths Generated */}
      {forecastReport && forecastReport.paths && forecastReport.paths.length > 0 && (
        <div className="space-y-2.5 pt-3 border-t border-surface-border">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Route className="h-4 w-4 text-brand-periwinkle" />
              <span className="text-xs font-semibold text-white tracking-wide">
                Simulated future trajectories ({forecastReport.paths_generated_count} paths)
              </span>
            </div>
            <span className="text-[11px] text-slate-400">
              Evaluated across {forecastReport.scenarios_evaluated_count} future scenarios
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 max-h-52 overflow-y-auto pr-1">
            {forecastReport.paths.map((path) => (
              <div
                key={path.path_id}
                className="p-3 rounded-lg bg-surface-raised border border-surface-border space-y-2"
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="text-brand-periwinkle font-medium font-mono">
                    {path.path_id}
                  </span>
                  <span className="text-xs font-semibold text-brand-columbia bg-brand-primary/10 px-2 py-0.5 rounded border border-brand-primary/30 font-mono">
                    Cumulative: {(path.cumulative_probability * 100).toFixed(1)}%
                  </span>
                </div>

                <div className="flex items-center gap-1.5 text-xs text-slate-200 flex-wrap">
                  {path.accounts_sequence.map((acct, idx) => (
                    <React.Fragment key={idx}>
                      <span className="px-1.5 py-0.5 rounded bg-surface-card text-slate-200 border border-surface-border font-mono text-[11px]">
                        {acct}
                      </span>
                      {idx < path.accounts_sequence.length - 1 && (
                        <ArrowRight className="h-3 w-3 text-brand-periwinkle shrink-0" />
                      )}
                    </React.Fragment>
                  ))}
                </div>

                <div className="text-[11px] text-slate-400">
                  {path.hops.length} predicted hop{path.hops.length !== 1 ? "s" : ""} • Projected volume:{" "}
                  <span className="font-mono text-slate-300">
                    {formatMinorUnits(path.hops[0]?.amount_minor_units || 0)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Expandable Technical Details */}
      <div className="border-t border-surface-border pt-2">
        <button
          onClick={() => setShowTechnicalMath(!showTechnicalMath)}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors cursor-pointer"
        >
          {showTechnicalMath ? (
            <ChevronUp className="h-3.5 w-3.5 text-brand-periwinkle" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-brand-periwinkle" />
          )}
          <span>{showTechnicalMath ? "Hide algorithmic probability details" : "Show algorithmic probability calculation details"}</span>
        </button>

        {showTechnicalMath && (
          <div className="mt-2.5 p-3.5 rounded-lg bg-surface-card border border-surface-border text-xs text-slate-400 space-y-2">
            <div className="flex items-center gap-1.5 text-slate-200 font-medium">
              <Info className="h-3.5 w-3.5 text-brand-columbia" />
              <span>Mathematical Calibration &amp; Normalization</span>
            </div>
            <p>
              Next-hop ranking applies a log-linear model with graph heuristics (historical flow frequency, clustering coefficient, and temporal recency). Raw logits are normalized across candidate sets via softmax: <span className="font-mono text-slate-300">P(i) = exp(s_i) / Σ exp(s_j)</span>. When candidate set size is 1, the output collapses to 1.0. Investigators should treat this as ordinal ranking rather than an actuarial survival probability.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
