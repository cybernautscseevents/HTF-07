"use client";

import React from "react";
import { AlertTriangle, Activity, ShieldAlert } from "lucide-react";
import { StageReport } from "@/types";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { getStageBadge } from "@/lib/mappers/analysisMapper";

interface EvidenceWarningsPanelProps {
  warnings: string[];
  stages?: Record<string, StageReport>;
  analysisTimestamp?: string;
  overallStatus?: string;
}

export function EvidenceWarningsPanel({
  warnings,
  stages = {},
  analysisTimestamp,
  overallStatus,
}: EvidenceWarningsPanelProps) {
  const stageEntries = Object.entries(stages);
  const totalStages = stageEntries.length;
  const availableStages = stageEntries.filter(([, report]) => report.status === "available").length;
  const allStagesAvailable = totalStages > 0 && availableStages === totalStages;

  return (
    <div className="rounded-xl border border-surface-border bg-surface-elevated p-4 lg:p-5 space-y-4 shadow-xl">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-surface-border">
        <div>
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-brand-periwinkle" />
            <h2 className="text-sm font-semibold text-white tracking-wide">
              Evidence and limitations
            </h2>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Audit trail of pipeline subsystem completeness, graph constraints, and known assumptions.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {overallStatus && (
            <StatusBadge
              label={`Pipeline: ${overallStatus.replace(/_/g, " ")}`}
              variant={overallStatus === "completed" ? "success" : "warning"}
              size="sm"
            />
          )}
          {totalStages > 0 && (
            <StatusBadge
              label={
                allStagesAvailable
                  ? `${totalStages}/${totalStages} stages verified`
                  : `${availableStages}/${totalStages} stages active`
              }
              variant={allStagesAvailable ? "success" : "neutral"}
              size="sm"
            />
          )}
        </div>
      </div>

      {/* Honest Stage Completeness Notice */}
      {totalStages > 0 && !allStagesAvailable && (
        <div className="p-3.5 rounded-lg bg-surface-raised border border-risk-caution/30 text-xs text-slate-300 leading-relaxed flex items-start gap-2.5">
          <AlertTriangle className="h-4 w-4 text-risk-caution shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold text-slate-200">
              Partial pipeline availability notice:
            </span>
            <p className="text-slate-400 mt-0.5">
              The analysis executed successfully, but {totalStages - availableStages} out of {totalStages} subsystem stages (such as machine learning risk scoring) are operating with fallback or offline artifacts. Hold decisions remain grounded in deterministic money flow and min-cut topology.
            </p>
          </div>
        </div>
      )}

      {/* System Constraints and Limitations */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-slate-300">
          System constraints and algorithmic boundaries:
        </div>
        <div className="space-y-2">
          {warnings.length === 0 ? (
            <div className="p-3 rounded-lg bg-surface-raised border border-surface-border text-xs text-slate-400">
              No operational constraints or limitations logged for this analysis run.
            </div>
          ) : (
            warnings.map((w, idx) => (
              <div
                key={idx}
                className="flex items-start gap-2.5 p-3 rounded-lg bg-surface-raised border border-surface-border text-xs text-slate-300 leading-relaxed"
              >
                <AlertTriangle className="h-4 w-4 text-risk-caution shrink-0 mt-0.5" />
                <span>{w}</span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Subsystem Stage Diagnostics */}
      {stageEntries.length > 0 && (
        <div className="space-y-2.5 pt-3 border-t border-surface-border">
          <div className="text-xs font-medium text-slate-300 flex items-center gap-2">
            <Activity className="h-4 w-4 text-brand-periwinkle" />
            <span>Subsystem execution verification matrix</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
            {stageEntries.map(([stageName, report]) => {
              const badge = getStageBadge(report.status);

              return (
                <div
                  key={stageName}
                  className="p-3 rounded-lg bg-surface-raised border border-surface-border space-y-1.5 text-xs"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-white font-medium capitalize text-xs">
                      {stageName.replace(/_/g, " ")}
                    </span>
                    <StatusBadge
                      label={badge.label}
                      variant={badge.variant}
                      size="sm"
                    />
                  </div>

                  {report.message && (
                    <div className="text-[11px] text-slate-400 leading-tight">
                      {report.message}
                    </div>
                  )}

                  {report.details && Object.keys(report.details).length > 0 && (
                    <div className="text-[10px] text-slate-500 pt-1 border-t border-surface-border font-mono">
                      {Object.entries(report.details)
                        .slice(0, 3)
                        .map(([k, v]) => `${k}: ${v}`)
                        .join(" • ")}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {analysisTimestamp && (
        <div className="text-[11px] text-slate-500 pt-2 border-t border-surface-border flex items-center justify-between font-mono">
          <span>Engine execution audit record</span>
          <span>Computed: {new Date(analysisTimestamp).toUTCString()}</span>
        </div>
      )}
    </div>
  );
}
