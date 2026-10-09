"use client";

import React from "react";
import { ShieldCheck, RefreshCw, Zap, FolderPlus, Activity, ChevronDown } from "lucide-react";
import { FraudCase } from "@/types";

interface NavbarProps {
  cases: FraudCase[];
  activeCaseId: string;
  onSelectCase: (caseId: string) => void;
  onLoadDemo: () => void;
  onNewCase: () => void;
  isLoadingDemo: boolean;
  isBackendHealthy: boolean;
}

export function Navbar({
  cases,
  activeCaseId,
  onSelectCase,
  onLoadDemo,
  onNewCase,
  isLoadingDemo,
  isBackendHealthy,
}: NavbarProps) {
  return (
    <header className="sticky top-0 z-50 flex h-14 items-center justify-between border-b border-[#23233c] bg-[#0c0c16]/95 px-4 lg:px-6 backdrop-blur-md font-sans">
      {/* Brand & System Status */}
      <div className="flex items-center gap-5">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#6666ff] text-white shadow-sm ring-1 ring-white/20">
            <ShieldCheck className="h-4.5 w-4.5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-sm tracking-tight text-white font-sans">
                AEGIS-Flow
              </span>
              <span className="text-[10px] font-sans px-2 py-0.5 rounded-full bg-[#17172b] text-[#b0baff] border border-[#23233c]">
                Fraud Investigation Workstation
              </span>
            </div>
            <p className="text-[11px] text-slate-400 font-sans hidden sm:block">
              Decision support and temporal intervention analysis
            </p>
          </div>
        </div>

        {/* Live Engine Status Indicator */}
        <div className="hidden md:flex items-center gap-2 border-l border-[#23233c] pl-4">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#121222] border border-[#23233c] text-xs font-sans">
            <span
              className={`h-2 w-2 rounded-full ${
                isBackendHealthy
                  ? "bg-[#b9f0d7]"
                  : "bg-[#e05263]"
              }`}
            />
            <span className={isBackendHealthy ? "text-[#b9f0d7]" : "text-[#e05263]"}>
              {isBackendHealthy ? "Analysis engine active" : "Engine disconnected"}
            </span>
          </div>
        </div>
      </div>

      {/* Case Selection & Primary Actions */}
      <div className="flex items-center gap-2.5">
        {/* Case Selector Dropdown */}
        <div className="relative flex items-center bg-[#121222] border border-[#23233c] rounded-lg px-2.5 py-1 text-xs hover:border-[#3b3b5c] transition-colors">
          <Activity className="h-3.5 w-3.5 text-slate-400 mr-1.5 shrink-0" />
          <span className="text-slate-400 mr-1 text-[11px] font-sans">Case:</span>
          <select
            value={activeCaseId}
            onChange={(e) => onSelectCase(e.target.value)}
            className="bg-transparent text-xs text-slate-200 outline-none cursor-pointer pr-5 max-w-[190px] sm:max-w-[260px] truncate font-mono"
          >
            {cases.length === 0 && <option value="">No cases loaded</option>}
            {cases.map((c) => (
              <option key={c.case_id} value={c.case_id} className="bg-[#121222] text-slate-200">
                {c.case_id} {c.title ? `— ${c.title}` : ""}
              </option>
            ))}
          </select>
          <ChevronDown className="h-3 w-3 text-slate-400 pointer-events-none absolute right-2" />
        </div>

        {/* Load Demo Case Button (High Priority Action) */}
        <button
          onClick={onLoadDemo}
          disabled={isLoadingDemo}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[#6666ff] hover:bg-[#5252ee] active:bg-[#4343d8] px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer focus:outline-none focus:ring-2 focus:ring-[#6666ff]/50"
          title="Initialize deterministic synthetic scenario 'Operation ShatterFlow' via live API"
        >
          {isLoadingDemo ? (
            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Zap className="h-3.5 w-3.5 text-[#c9e8ff]" />
          )}
          <span>{isLoadingDemo ? "Loading demo..." : "Load demo case"}</span>
        </button>

        {/* New Case Button */}
        <button
          onClick={onNewCase}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[#17172b] hover:bg-[#20203a] px-3 py-1.5 text-xs font-medium text-slate-200 transition-colors cursor-pointer border border-[#23233c] focus:outline-none focus:ring-2 focus:ring-[#6666ff]/40"
          title="Create a new custom investigation case"
        >
          <FolderPlus className="h-3.5 w-3.5 text-slate-400" />
          <span className="hidden sm:inline">New case</span>
        </button>
      </div>
    </header>
  );
}

