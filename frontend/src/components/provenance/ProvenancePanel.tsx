"use client";

import React, { useState } from "react";
import { GitFork, Info, ShieldAlert, ChevronDown, ChevronUp } from "lucide-react";
import { TaintSummary } from "@/types";
import { formatMinorUnits, formatPaise } from "@/lib/currency";
import { MetricCard } from "@/components/ui/MetricCard";

interface ProvenancePanelProps {
  taintSummary: TaintSummary | null;
  selectedRecommendationIntercepted?: number;
}

export function ProvenancePanel({
  taintSummary,
  selectedRecommendationIntercepted,
}: ProvenancePanelProps) {
  const [showTechnicalDetails, setShowTechnicalDetails] = useState<boolean>(false);

  if (!taintSummary) {
    return (
      <div className="rounded-xl border border-surface-border bg-surface-elevated p-6 text-sm text-slate-400 text-center">
        No provenance metrics computed. Run the investigation analysis to trace fund movements.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-surface-border bg-surface-elevated p-4 lg:p-5 space-y-4 shadow-xl">
      {/* Title & Method Badge */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-surface-border">
        <div>
          <div className="flex items-center gap-2">
            <GitFork className="h-4 w-4 text-brand-periwinkle" />
            <h2 className="text-sm font-semibold text-white tracking-wide">
              Money trail
            </h2>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Tracking where reported funds traveled across pooled accounts through the selected decision time.
          </p>
        </div>
        <span className="text-[11px] font-sans px-2.5 py-1 rounded-full bg-surface-raised border border-surface-border text-slate-300">
          Proportional pool allocation
        </span>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          label="Propagated tainted volume"
          value={formatMinorUnits(taintSummary.total_propagated_volume_minor_units)}
          subvalue={formatPaise(taintSummary.total_propagated_volume_minor_units)}
          accent="red"
          tooltip="Total volume of reported tainted money tracked through transactions up to decision timestamp"
        />

        <MetricCard
          label="Active tainted accounts"
          value={String(taintSummary.current_tainted_account_count)}
          subvalue={`${taintSummary.seed_count} seed injection point${taintSummary.seed_count !== 1 ? "s" : ""}`}
          accent="amber"
          tooltip="Accounts currently holding active modeled taint balances at the decision timestamp"
        />

        <MetricCard
          label="Attributed transfer edges"
          value={String(taintSummary.allocated_edge_count)}
          subvalue={`${taintSummary.shortfall_count} shortfall event${taintSummary.shortfall_count !== 1 ? "s" : ""}`}
          accent="default"
          tooltip="Transaction paths over which taint was propagated chronologically"
        />

        <MetricCard
          label="Intercepted by recommended hold"
          value={
            selectedRecommendationIntercepted != null
              ? formatMinorUnits(selectedRecommendationIntercepted)
              : "Pending hold"
          }
          subvalue="Selected hold recovery"
          accent="emerald"
          tooltip="Illicit capital intercepted by the recommended intervention point"
        />
      </div>

      {/* Currently Tainted Accounts */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-slate-300">
          Accounts holding modeled taint balances at decision time:
        </div>

        {taintSummary.current_tainted_accounts.length === 0 ? (
          <div className="p-3 rounded-lg bg-surface-raised border border-surface-border text-xs text-slate-400 italic">
            No accounts hold active taint balances at this decision timestamp.
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {taintSummary.current_tainted_accounts.map((acct) => (
              <div
                key={acct}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-risk-danger/10 border border-risk-danger/30 text-xs text-rose-300 font-mono"
              >
                <span className="h-2 w-2 rounded-full bg-risk-danger shadow-[0_0_6px_rgba(224,82,99,0.5)]" />
                <span className="font-semibold select-all">{acct}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Trust & Legal Context Notice */}
      <div className="rounded-lg bg-surface-raised border border-surface-border p-4 space-y-2 text-xs text-slate-300 leading-relaxed">
        <div className="flex items-center gap-2 font-semibold text-slate-200">
          <ShieldAlert className="h-4 w-4 text-brand-periwinkle shrink-0" />
          <span>Attribution methodology &amp; legal boundary</span>
        </div>
        <p>
          Modeled money flow uses <strong>proportional allocation with integer largest-remainder rounding (Hamilton-Hare method)</strong> to conserve flow across commingled pooled accounts.
        </p>
        <p className="text-slate-400">
          This mathematical attribution represents algorithmic tracking of funds for investigator decision support. It does <strong>not</strong> constitute statutory legal proof of criminal intent, regulatory guilt, or confirmation of live banking freezes.
        </p>
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
          <span>{showTechnicalDetails ? "Hide technical conservation mechanics" : "Show technical conservation mechanics & simulation assumptions"}</span>
        </button>

        {showTechnicalDetails && (
          <div className="mt-2.5 p-3.5 rounded-lg bg-surface-card border border-surface-border text-xs text-slate-400 space-y-2">
            <div className="flex items-center gap-1.5 text-slate-200 font-medium">
              <Info className="h-3.5 w-3.5 text-brand-columbia" />
              <span>Additive Collateral Approximation Notice</span>
            </div>
            <p>
              When evaluating individual hold points, counterfactual collateral estimates assume independent single-edge interventions. If multiple holds are executed simultaneously across shared intermediary accounts, joint non-linear commingling dynamics may lead to different collateral sums than simple addition.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
