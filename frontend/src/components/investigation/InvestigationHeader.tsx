"use client";

import React from "react";
import {
  Play,
  AlertTriangle,
  Clock,
  CheckCircle2,
  Calendar,
  Layers,
  ArrowRight,
} from "lucide-react";
import { FraudCase, InvestigationAnalysisResponse } from "@/types";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { isAnalysisStale } from "@/lib/mappers/analysisMapper";

interface InvestigationHeaderProps {
  currentCase: FraudCase | null;
  eventsCount: number;
  decisionTimestamp: string;
  analysis: InvestigationAnalysisResponse | null;
  isAnalyzing: boolean;
  onRunAnalysis: () => void;
  reportedAmountMinorUnits?: number;
}

export function InvestigationHeader({
  currentCase,
  eventsCount,
  decisionTimestamp,
  analysis,
  isAnalyzing,
  onRunAnalysis,
  reportedAmountMinorUnits,
}: InvestigationHeaderProps) {
  if (!currentCase) {
    return (
      <div className="border-b border-[#23233c] bg-[#121222] p-4 text-center text-xs text-slate-400 font-sans">
        No investigation selected. Load a demo case or create a new record to begin.
      </div>
    );
  }

  const isStale = isAnalysisStale(analysis, decisionTimestamp);

  // Pipeline completeness
  const stages = analysis?.stages || {};
  const stageEntries = Object.entries(stages);
  const completedStagesCount = stageEntries.filter(
    ([, s]) => s.status === "completed" || s.status === "available"
  ).length;
  const allStagesAvailable = stageEntries.length > 0 && completedStagesCount === stageEntries.length;
  const unavailableStages = stageEntries.filter(
    ([, s]) => s.status === "unavailable" || s.status === "failed" || s.status === "insufficient_evidence"
  );

  return (
    <div className="border-b border-[#23233c] bg-[#121222] px-4 py-4 lg:px-6 font-sans">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        {/* Left: Case Summary & Core Facts (Question 1: What happened?) */}
        <div className="space-y-2 max-w-4xl">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-lg font-bold text-white tracking-tight">
              {currentCase.title}
            </h1>
            <span className="font-mono text-xs px-2.5 py-0.5 rounded-full bg-[#17172b] text-[#b0baff] border border-[#23233c] font-semibold select-all">
              {currentCase.case_id}
            </span>
            <StatusBadge
              label={currentCase.status === "open" ? "Open case" : currentCase.status.replace(/_/g, " ")}
              variant="neutral"
              size="sm"
            />
            {currentCase.origin === "synthetic" && (
              <span className="text-[11px] font-sans bg-[#e5a84b]/10 text-[#e5a84b] border border-[#e5a84b]/30 px-2.5 py-0.5 rounded-full">
                Synthetic benchmark
              </span>
            )}
          </div>

          <p className="text-xs text-slate-300 leading-relaxed max-w-3xl">
            {currentCase.description || "Active multi-hop financial crime investigation."}
          </p>

          {/* Quick Forensic Strip */}
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs text-slate-400 pt-1">
            <span className="flex items-center gap-1.5">
              <Calendar className="h-3.5 w-3.5 text-slate-500" />
              <span>Opened: <strong className="text-slate-300 font-normal">{new Date(currentCase.opened_at).toLocaleDateString()}</strong></span>
            </span>

            <span className="flex items-center gap-1.5">
              <Layers className="h-3.5 w-3.5 text-slate-500" />
              <span>Observed transfers: <strong className="text-slate-200 font-semibold">{eventsCount}</strong></span>
            </span>

            {reportedAmountMinorUnits != null && reportedAmountMinorUnits > 0 && (
              <span className="flex items-center gap-1.5 text-[#e05263] font-medium" title="Initial fraudulent transfer amount">
                <span>Reported fraud: <strong className="font-mono text-white">₹{(reportedAmountMinorUnits / 100).toLocaleString("en-IN")}</strong></span>
              </span>
            )}

            <span className="flex items-center gap-1.5 text-[#c9e8ff]">
              <Clock className="h-3.5 w-3.5 text-[#6666ff]" />
              <span>Decision cutoff T: <strong className="font-mono text-white">{decisionTimestamp.slice(11, 19)} UTC</strong></span>
            </span>
          </div>
        </div>

        {/* Right: Freshness Status & Prioritized Action Button */}
        <div className="flex flex-wrap items-center gap-3 self-start lg:self-center shrink-0">
          {/* Analysis Freshness / Pipeline Completeness */}
          {analysis && !isStale && (
            <div
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs ${
                allStagesAvailable
                  ? "bg-[#b9f0d7]/10 border-[#b9f0d7]/30 text-[#b9f0d7]"
                  : "bg-[#17172b] border-[#23233c] text-slate-300"
              }`}
            >
              <CheckCircle2
                className={`h-4 w-4 shrink-0 ${allStagesAvailable ? "text-[#b9f0d7]" : "text-[#b0baff]"}`}
              />
              <div>
                <div className="font-semibold text-xs leading-none">
                  {allStagesAvailable ? "Analysis complete" : "Analysis complete (partial stages)"}
                </div>
                <div className="text-[11px] text-slate-400 mt-0.5">
                  {allStagesAvailable
                    ? "All 7 stages available"
                    : `${completedStagesCount}/${stageEntries.length} stages active • ${unavailableStages.length} unconfigured`}
                </div>
              </div>
            </div>
          )}

          {isStale && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#e5a84b]/10 border border-[#e5a84b]/30 text-xs">
              <AlertTriangle className="h-4 w-4 text-[#e5a84b] shrink-0" />
              <div>
                <div className="font-semibold text-[#e5a84b] text-xs leading-none">
                  Timeline adjusted
                </div>
                <div className="text-[11px] text-[#e5a84b]/80 mt-0.5">
                  Recalculation required for time T
                </div>
              </div>
            </div>
          )}

          {!analysis && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#17172b] border border-[#23233c] text-xs text-slate-400">
              <Clock className="h-3.5 w-3.5 text-slate-400" />
              <span>Awaiting analysis</span>
            </div>
          )}

          {/* Single Prioritized Action Button */}
          <button
            onClick={onRunAnalysis}
            disabled={isAnalyzing}
            className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold tracking-normal text-white shadow-md transition-all cursor-pointer focus:outline-none focus:ring-2 ${
              isStale
                ? "bg-[#e5a84b] hover:bg-[#d49638] text-slate-950 font-bold focus:ring-[#e5a84b]/50"
                : "bg-[#6666ff] hover:bg-[#5252ee] active:bg-[#4343d8] focus:ring-[#6666ff]/50"
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            <Play className={`h-3.5 w-3.5 fill-current ${isAnalyzing ? "animate-spin" : ""}`} />
            <span>
              {isAnalyzing
                ? "Analyzing..."
                : isStale
                ? "Recalculate at time T"
                : "Run investigation analysis"}
            </span>
            {!isAnalyzing && <ArrowRight className="h-3 w-3 opacity-80" />}
          </button>
        </div>
      </div>
    </div>
  );
}
