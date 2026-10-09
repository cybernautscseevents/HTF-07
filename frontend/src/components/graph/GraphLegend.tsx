import React from "react";

export function GraphLegend() {
  return (
    <div className="flex flex-wrap items-center justify-between gap-y-2 gap-x-4 text-xs text-slate-300 font-sans px-3 py-1.5 rounded-xl bg-[#121222]/90 border border-[#23233c] backdrop-blur-sm">
      <div className="flex flex-wrap items-center gap-4">
        {/* Nodes */}
        <div className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-[#e05263]" />
          <span className="text-slate-200">Tainted / Seed</span>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-[#b0baff]" />
          <span className="text-slate-200">Exit sink</span>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-slate-500" />
          <span className="text-slate-300">Clean intermediary</span>
        </div>

        <span className="text-slate-700 hidden sm:inline">|</span>

        {/* Edges */}
        <div className="flex items-center gap-1.5">
          <span className="w-3.5 h-0.5 bg-slate-400 inline-block rounded" />
          <span className="text-slate-200">Observed transfer (&le; T)</span>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="w-3.5 h-0.5 border-b border-dotted border-[#e5a84b] inline-block" />
          <span className="text-[#e5a84b]">Later observation (&gt; T)</span>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="w-3.5 h-0.5 border-b border-dashed border-[#b0baff] inline-block" />
          <span className="text-[#b0baff]">Simulated forecast</span>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="w-3.5 h-1 bg-[#e05263] inline-block rounded" />
          <span className="text-[#e05263] font-semibold">Chokepoint barrier</span>
        </div>
      </div>

      <div className="text-[11px] text-slate-400 hidden md:block">
        Click node or edge for detailed inspection
      </div>
    </div>
  );
}

