"use client";

import React, { useEffect } from "react";
import { X, ArrowRight, AlertOctagon, Cpu } from "lucide-react";
import { SelectedEntity } from "@/types";
import { formatMinorUnits, formatPaise } from "@/lib/currency";
import { StatusBadge } from "@/components/ui/StatusBadge";

interface EntityInspectorProps {
  selectedEntity: SelectedEntity;
  onClose: () => void;
}

export function EntityInspector({
  selectedEntity,
  onClose,
}: EntityInspectorProps) {
  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  if (!selectedEntity) return null;

  return (
    <div className="absolute right-3 top-3 bottom-3 w-88 max-w-[calc(100%-24px)] rounded-2xl border border-[#23233c] bg-[#121222]/95 p-4 shadow-2xl backdrop-blur-md z-30 flex flex-col justify-between overflow-y-auto font-sans transition-all">
      <div>
        {/* Header */}
        <div className="flex items-center justify-between pb-3 border-b border-[#23233c]">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-sans uppercase px-2.5 py-0.5 rounded-full bg-[#17172b] text-[#b0baff] font-semibold border border-[#23233c]">
              {selectedEntity.type === "node" ? "Account entity" : "Financial transfer"}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-[#17172b] text-slate-400 hover:text-white transition-colors cursor-pointer"
            title="Close inspector (Esc)"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Content for Node */}
        {selectedEntity.type === "node" && (
          <div className="space-y-4 pt-3 text-xs">
            <div>
              <div className="text-[10px] uppercase font-sans text-slate-400 tracking-wider">
                Account Identifier
              </div>
              <div className="text-sm font-bold text-white font-mono break-all mt-0.5 select-all">
                {selectedEntity.data.account_id}
              </div>
            </div>

            {/* Badges */}
            <div className="flex flex-wrap gap-1.5">
              {selectedEntity.data.isTainted && (
                <StatusBadge label="Tainted proceeds" variant="danger" size="sm" />
              )}
              {selectedEntity.data.isSink && (
                <StatusBadge label="Designated exit sink" variant="purple" size="sm" />
              )}
              {selectedEntity.data.isSeed && (
                <StatusBadge label="Fraud seed destination" variant="warning" size="sm" />
              )}
              {!selectedEntity.data.isTainted && !selectedEntity.data.isSink && !selectedEntity.data.isSeed && (
                <StatusBadge label="Intermediary account" variant="neutral" size="sm" />
              )}
            </div>

            {/* Flow Totals */}
            <div className="grid grid-cols-2 gap-2 pt-1 font-sans">
              <div className="p-3 rounded-xl bg-[#0c0c16]/80 border border-[#23233c]">
                <div className="text-[10px] text-slate-400 font-sans">Observed Inflow</div>
                <div className="text-xs font-bold text-slate-100 font-mono mt-1">
                  {formatMinorUnits(selectedEntity.data.totalInflowMinorUnits)}
                </div>
              </div>
              <div className="p-3 rounded-xl bg-[#0c0c16]/80 border border-[#23233c]">
                <div className="text-[10px] text-slate-400 font-sans">Observed Outflow</div>
                <div className="text-xs font-bold text-slate-100 font-mono mt-1">
                  {formatMinorUnits(selectedEntity.data.totalOutflowMinorUnits)}
                </div>
              </div>
            </div>

            {/* ML Mule Risk Score */}
            <div className="p-3.5 rounded-xl bg-[#17172b] border border-[#23233c] space-y-2 font-sans">
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                  <Cpu className="h-3.5 w-3.5 text-[#6666ff]" />
                  <span>Mule risk score</span>
                </span>
                {selectedEntity.data.riskLevel ? (
                  <StatusBadge
                    label={selectedEntity.data.riskLevel}
                    variant={
                      selectedEntity.data.riskLevel === "HIGH" ||
                      selectedEntity.data.riskLevel === "CRITICAL"
                        ? "danger"
                        : "warning"
                    }
                    size="sm"
                  />
                ) : (
                  <span className="text-[11px] text-slate-500 font-sans">Unscored</span>
                )}
              </div>

              {selectedEntity.data.riskScore != null ? (
                <div className="space-y-1">
                  <div className="text-xs text-slate-300">
                    Calculated risk:{" "}
                    <strong className="text-[#e05263] font-bold text-sm font-mono">
                      {(selectedEntity.data.riskScore * 100).toFixed(1)}%
                    </strong>
                  </div>
                  <div className="text-[11px] text-slate-400 font-sans leading-relaxed">
                    Evaluated against supervised graph feature classifier up to decision time T.
                  </div>
                </div>
              ) : (
                <div className="text-[11px] text-slate-400 font-sans">
                  Risk scoring artifact was not evaluated or account was clean source. No scores fabricated.
                </div>
              )}
            </div>
          </div>
        )}

        {/* Content for Edge */}
        {selectedEntity.type === "edge" && (
          <div className="space-y-4 pt-3 text-xs">
            <div>
              <div className="text-[10px] uppercase font-sans text-slate-400 tracking-wider">
                {selectedEntity.data.isObserved ? "Confirmed transfer" : "Forecasted trajectory hop"}
              </div>
              <div className="text-sm font-bold text-white font-mono break-all mt-0.5 select-all">
                {selectedEntity.data.id}
              </div>
            </div>

            {/* Transfer Routing */}
            <div className="p-3 rounded-xl bg-[#0c0c16]/80 border border-[#23233c] space-y-2 font-sans">
              <div>
                <span className="text-[10px] text-slate-400 uppercase font-sans">Debited Account</span>
                <div className="text-xs text-slate-200 font-semibold font-mono truncate">
                  {selectedEntity.data.source}
                </div>
              </div>

              <div className="flex items-center justify-center text-slate-400 my-0.5">
                <ArrowRight className="h-4 w-4 text-[#6666ff]" />
              </div>

              <div>
                <span className="text-[10px] text-slate-400 uppercase font-sans">Credited Account</span>
                <div className="text-xs text-slate-200 font-semibold font-mono truncate">
                  {selectedEntity.data.target}
                </div>
              </div>
            </div>

            {/* Amount details */}
            <div className="p-3.5 rounded-xl bg-[#17172b] border border-[#23233c] space-y-1">
              <span className="text-[10px] text-slate-400 uppercase tracking-wider font-sans">Transfer Amount</span>
              <div className="text-lg font-bold text-white font-mono">
                {formatMinorUnits(selectedEntity.data.amountMinorUnits, selectedEntity.data.currency)}
              </div>
              <div className="text-[11px] text-slate-400 font-mono">
                {formatPaise(selectedEntity.data.amountMinorUnits)}
              </div>
            </div>

            {/* Status & Timing */}
            <div className="space-y-2 text-xs text-slate-300 font-sans">
              <div className="flex justify-between py-1 border-b border-[#23233c]">
                <span className="text-slate-400">Timestamp:</span>
                <span className="font-mono text-slate-200">{selectedEntity.data.occurredAt.replace("T", " ").replace("Z", " UTC")}</span>
              </div>
              {selectedEntity.data.channel && (
                <div className="flex justify-between py-1 border-b border-[#23233c]">
                  <span className="text-slate-400">Payment rail:</span>
                  <span className="uppercase text-slate-200 font-mono text-[11px]">{selectedEntity.data.channel}</span>
                </div>
              )}
              {selectedEntity.data.probability != null && (
                <div className="flex justify-between py-1 border-b border-[#23233c]">
                  <span className="text-slate-400">Forecast confidence:</span>
                  <span className="text-[#c9e8ff] font-semibold font-mono">
                    {(selectedEntity.data.probability * 100).toFixed(1)}%
                  </span>
                </div>
              )}
              {selectedEntity.data.isCutEdge && (
                <div className="mt-2 p-2.5 rounded-lg bg-[#e05263]/10 border border-[#e05263]/30 text-[#e05263] flex items-center gap-2">
                  <AlertOctagon className="h-4 w-4 shrink-0 text-[#e05263]" />
                  <span className="font-medium text-xs">Identified chokepoint barrier edge</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="pt-3 border-t border-[#23233c] text-[11px] text-slate-400 font-sans flex items-center justify-between">
        <span>Press Esc to close</span>
        <span className="font-mono text-[10px] text-slate-500">AEGIS-Flow</span>
      </div>
    </div>
  );
}

