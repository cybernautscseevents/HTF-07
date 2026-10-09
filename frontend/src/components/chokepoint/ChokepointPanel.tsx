"use client";

import React, { useState } from "react";
import { Scissors, ShieldCheck, AlertTriangle, CheckCircle, Lock, ChevronDown, ChevronUp, Info } from "lucide-react";
import { ChokepointReport, CandidateRecommendation } from "@/types";
import { formatMinorUnits } from "@/lib/currency";
import { StatusBadge } from "@/components/ui/StatusBadge";

interface ChokepointPanelProps {
  chokepointReport: ChokepointReport | null;
  selectedRecommendation: CandidateRecommendation | null;
  sourceAccounts?: string[];
  sinkAccounts?: string[];
}

export function ChokepointPanel({
  chokepointReport,
  selectedRecommendation,
  sourceAccounts = [],
  sinkAccounts = [],
}: ChokepointPanelProps) {
  const [showTechnicalDetails, setShowTechnicalDetails] = useState<boolean>(false);

  if (!chokepointReport) {
    return (
      <div className="rounded-xl border border-surface-border bg-surface-elevated p-5 text-sm text-slate-400 text-center">
        Temporal chokepoint search is awaiting cash-out sink specification.
      </div>
    );
  }

  const isCutOptimal =
    chokepointReport.status === "optimal_cut_found" ||
    chokepointReport.is_cut_verified;

  return (
    <div className="rounded-xl border border-surface-border bg-surface-elevated p-4 lg:p-5 space-y-4 shadow-xl">
      {/* Title */}
      <div className="flex items-center justify-between pb-3 border-b border-surface-border">
        <div className="flex items-center gap-2">
          <Scissors className="h-4 w-4 text-brand-periwinkle" />
          <h2 className="text-sm font-semibold text-white tracking-wide">
            Temporal min-cut chokepoint barrier
          </h2>
        </div>
        <StatusBadge
          label={chokepointReport.status.replace(/_/g, " ")}
          variant={isCutOptimal ? "success" : "warning"}
          size="sm"
        />
      </div>

      {/* Distinction Banner: Cut-Set vs Single Edge Hold */}
      <div className="p-4 rounded-lg bg-surface-raised border border-surface-border space-y-2 text-xs leading-relaxed text-slate-300">
        <div className="flex items-center gap-2 text-slate-100 font-semibold text-xs">
          <ShieldCheck className="h-4 w-4 text-brand-celadon" />
          <span>Complete multi-edge cut set vs. single candidate hold</span>
        </div>
        <p>
          A <strong className="text-brand-celadon">Complete cut set</strong> (holding {chokepointReport.cut_size} transfer{chokepointReport.cut_size !== 1 ? "s" : ""} simultaneously) provably disconnects <em>every</em> modeled flow path from source to sink.
        </p>
        <p className="text-slate-400">
          In contrast, individual <strong className="text-brand-columbia">Single-edge holds</strong> intercept a specific transaction, but parallel branches may allow funds to bypass unless the full cut set is secured.
        </p>
      </div>

      {/* Sources and Sinks Configuration */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
        <div className="p-3 rounded-lg bg-surface-raised border border-surface-border">
          <span className="text-[11px] font-medium text-slate-400 block tracking-wide">
            Protected source accounts:
          </span>
          <div className="text-slate-200 mt-1.5 flex flex-wrap gap-1.5 font-mono">
            {sourceAccounts.length > 0 ? (
              sourceAccounts.map((s) => (
                <span key={s} className="px-2 py-0.5 rounded bg-surface-card border border-surface-border text-xs">
                  {s}
                </span>
              ))
            ) : (
              <span className="text-slate-500 italic">Default seed receivers</span>
            )}
          </div>
        </div>

        <div className="p-3 rounded-lg bg-surface-raised border border-surface-border">
          <span className="text-[11px] font-medium text-slate-400 block tracking-wide">
            Target cash-out exit sinks:
          </span>
          <div className="text-slate-200 mt-1.5 flex flex-wrap gap-1.5 font-mono">
            {sinkAccounts.length > 0 ? (
              sinkAccounts.map((s) => (
                <span key={s} className="px-2 py-0.5 rounded bg-brand-primary/20 border border-brand-primary/40 text-brand-columbia text-xs font-medium">
                  {s}
                </span>
              ))
            ) : (
              <span className="text-slate-500 italic">None specified</span>
            )}
          </div>
        </div>
      </div>

      {/* Key Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="p-3 rounded-lg bg-surface-raised border border-surface-border">
          <div className="text-[11px] font-medium text-slate-400">Cut set size</div>
          <div className="text-base font-semibold text-white mt-1">
            {chokepointReport.cut_size} transfer{chokepointReport.cut_size !== 1 ? "s" : ""}
          </div>
        </div>

        <div className="p-3 rounded-lg bg-surface-raised border border-surface-border">
          <div className="text-[11px] font-medium text-slate-400">Disconnection proof</div>
          <div className="text-base font-semibold mt-1 flex items-center gap-1.5">
            {chokepointReport.is_cut_verified ? (
              <>
                <CheckCircle className="h-4 w-4 text-brand-celadon" />
                <span className="text-brand-celadon text-sm font-medium">Verified isolated</span>
              </>
            ) : (
              <>
                <AlertTriangle className="h-4 w-4 text-risk-caution" />
                <span className="text-risk-caution text-sm font-medium">Unverified</span>
              </>
            )}
          </div>
        </div>

        <div className="p-3 rounded-lg bg-surface-raised border border-surface-border">
          <div className="text-[11px] font-medium text-slate-400">Estimated collateral</div>
          <div className="text-base font-semibold text-risk-caution font-mono mt-1">
            {formatMinorUnits(chokepointReport.total_estimated_collateral_minor_units)}
          </div>
        </div>

        <div className="p-3 rounded-lg bg-surface-raised border border-surface-border">
          <div className="text-[11px] font-medium text-slate-400">Optimization objective</div>
          <div className="text-base font-semibold text-brand-columbia font-mono mt-1">
            {chokepointReport.total_encoded_cut_cost.toLocaleString()}
          </div>
          <div className="text-[10px] text-slate-500 mt-0.5">Unitless graph penalty score</div>
        </div>
      </div>

      {/* Cut Set Members */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-slate-300">
          Identified complete cut set transfer identifiers:
        </div>

        {chokepointReport.cut_event_ids.length === 0 ? (
          <div className="p-3 rounded-lg bg-surface-raised border border-surface-border text-xs text-slate-400 italic font-mono">
            No active cut set members identified.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {chokepointReport.cut_event_ids.map((eventId) => {
              const isRecommended =
                selectedRecommendation?.target_event_id === eventId;

              return (
                <div
                  key={eventId}
                  className={`p-2.5 rounded-lg border font-mono text-xs flex items-center justify-between transition-colors ${
                    isRecommended
                      ? "bg-brand-primary/15 border-brand-primary/50 text-white shadow-sm"
                      : "bg-surface-raised border-surface-border text-slate-300"
                  }`}
                >
                  <div className="flex items-center gap-2 truncate">
                    <Lock className={`h-3.5 w-3.5 ${isRecommended ? "text-brand-celadon" : "text-brand-periwinkle"}`} />
                    <span className="truncate select-all">{eventId}</span>
                  </div>
                  {isRecommended && (
                    <span className="text-[10px] font-semibold text-brand-celadon bg-brand-celadon/10 px-2 py-0.5 rounded border border-brand-celadon/30 font-sans">
                      Recommended hold
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Expandable Technical Details */}
      <div className="border-t border-surface-border pt-2">
        <button
          onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors cursor-pointer"
        >
          {showTechnicalDetails ? (
            <ChevronUp className="h-3.5 w-3.5 text-brand-periwinkle" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-brand-periwinkle" />
          )}
          <span>{showTechnicalDetails ? "Hide technical min-cut formulation" : "Show technical min-cut formulation & objective details"}</span>
        </button>

        {showTechnicalDetails && (
          <div className="mt-2.5 p-3.5 rounded-lg bg-surface-card border border-surface-border text-xs text-slate-400 space-y-2">
            <div className="flex items-center gap-1.5 text-slate-200 font-medium">
              <Info className="h-3.5 w-3.5 text-brand-columbia" />
              <span>Algorithmic Objective Metric Note</span>
            </div>
            <p>
              The optimization cost of <span className="font-mono text-slate-200">{chokepointReport.total_encoded_cut_cost.toLocaleString()}</span> is a <strong>unitless capacity objective</strong> evaluated via Edmonds-Karp / Dinic min-cut algorithm. It penalizes edge disruptions based on policy weights and volume, and does <strong>not</strong> represent a financial currency balance.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
