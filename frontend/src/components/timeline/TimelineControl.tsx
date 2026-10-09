"use client";

import React from "react";
import { Clock, ChevronLeft, ChevronRight, FastForward, Rewind, AlertCircle } from "lucide-react";
import { TransactionEvent } from "@/types";
import { formatMinorUnits } from "@/lib/currency";

interface TimelineControlProps {
  events: TransactionEvent[];
  decisionTimestamp: string;
  onSelectTimestamp: (ts: string) => void;
  analysisTimestamp?: string;
}

export function TimelineControl({
  events,
  decisionTimestamp,
  onSelectTimestamp,
  analysisTimestamp,
}: TimelineControlProps) {
  if (events.length === 0) {
    return (
      <div className="p-3.5 text-xs text-slate-400 bg-[#121222] rounded-2xl border border-[#23233c] font-sans text-center">
        No active transaction timeline. Load a demo scenario to begin temporal replay.
      </div>
    );
  }

  // Sorted unique timestamps
  const sortedEvents = [...events].sort(
    (a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime()
  );

  const timestamps = Array.from(new Set(sortedEvents.map((e) => e.occurred_at)));
  const currentIndex = timestamps.findIndex((ts) => ts === decisionTimestamp);
  const activeIdx = currentIndex >= 0 ? currentIndex : timestamps.length - 1;

  const currentDecisionTime = new Date(decisionTimestamp).getTime();
  const availableEvents = sortedEvents.filter(
    (e) => new Date(e.occurred_at).getTime() <= currentDecisionTime
  );
  const futureEvents = sortedEvents.filter(
    (e) => new Date(e.occurred_at).getTime() > currentDecisionTime
  );

  const isStale = analysisTimestamp && analysisTimestamp !== decisionTimestamp;

  return (
    <div className="rounded-2xl border border-[#23233c] bg-[#121222] p-4 space-y-3.5 shadow-md font-sans">
      {/* Header and Step Controls */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-[#6666ff]" />
            <span className="text-xs font-bold text-white font-sans">
              Investigation timeline
            </span>
          </div>
          <span className="text-xs font-sans text-slate-400 bg-[#17172b] px-2.5 py-0.5 rounded-full border border-[#23233c]">
            Step {activeIdx + 1} of {timestamps.length}
          </span>
          {isStale && (
            <span className="inline-flex items-center gap-1.5 text-xs font-sans text-[#e5a84b] bg-[#e5a84b]/10 px-2.5 py-0.5 rounded-full border border-[#e5a84b]/30">
              <AlertCircle className="h-3 w-3" />
              <span>Awaiting recalculation at time T</span>
            </span>
          )}
        </div>

        {/* Playback & Step Controls */}
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => onSelectTimestamp(timestamps[0])}
            disabled={activeIdx === 0}
            className="p-1.5 rounded-lg bg-[#17172b] hover:bg-[#20203a] text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors border border-[#23233c] focus:outline-none focus:ring-1 focus:ring-[#6666ff]"
            title="Jump to initial fraud seed transfer (T0)"
          >
            <Rewind className="h-3.5 w-3.5" />
          </button>

          <button
            onClick={() => activeIdx > 0 && onSelectTimestamp(timestamps[activeIdx - 1])}
            disabled={activeIdx <= 0}
            className="p-1.5 rounded-lg bg-[#17172b] hover:bg-[#20203a] text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors border border-[#23233c] focus:outline-none focus:ring-1 focus:ring-[#6666ff]"
            title="Step back to previous transfer"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>

          <button
            onClick={() =>
              activeIdx < timestamps.length - 1 &&
              onSelectTimestamp(timestamps[activeIdx + 1])
            }
            disabled={activeIdx >= timestamps.length - 1}
            className="p-1.5 rounded-lg bg-[#17172b] hover:bg-[#20203a] text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors border border-[#23233c] focus:outline-none focus:ring-1 focus:ring-[#6666ff]"
            title="Step forward to next transfer"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>

          <button
            onClick={() => onSelectTimestamp(timestamps[timestamps.length - 1])}
            disabled={activeIdx === timestamps.length - 1}
            className="p-1.5 rounded-lg bg-[#17172b] hover:bg-[#20203a] text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors border border-[#23233c] focus:outline-none focus:ring-1 focus:ring-[#6666ff]"
            title="Jump to latest observed transaction"
          >
            <FastForward className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Scrubber / Slider */}
      <div className="space-y-2">
        <div className="relative flex items-center">
          <input
            type="range"
            min={0}
            max={timestamps.length - 1}
            value={activeIdx}
            onChange={(e) => {
              const idx = Number(e.target.value);
              if (timestamps[idx]) {
                onSelectTimestamp(timestamps[idx]);
              }
            }}
            className="w-full accent-[#6666ff] bg-[#17172b] h-2 rounded-lg cursor-pointer"
          />
        </div>

        <div className="flex items-center justify-between text-xs text-slate-400 font-sans">
          <span>Seed: <strong className="font-mono text-slate-300">{timestamps[0]?.slice(11, 19)} UTC</strong></span>
          <span className="text-[#c9e8ff] font-semibold bg-[#17172b] px-3 py-0.5 rounded-full border border-[#23233c]">
            Decision cutoff T = <strong className="font-mono text-white">{decisionTimestamp?.slice(11, 19)} UTC</strong>
          </span>
          <span>Latest: <strong className="font-mono text-slate-300">{timestamps[timestamps.length - 1]?.slice(11, 19)} UTC</strong></span>
        </div>
      </div>

      {/* Observation horizon breakdown & mini transaction list */}
      <div className="flex flex-wrap items-center justify-between text-xs pt-1.5 border-t border-[#23233c] gap-2">
        <div className="flex items-center gap-4 text-xs font-sans">
          <span className="text-slate-300 flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-[#b9f0d7] inline-block" />
            <span>Available evidence (&le; T):</span>
            <strong className="text-[#b9f0d7] font-semibold">{availableEvents.length} transfer{availableEvents.length !== 1 ? "s" : ""}</strong>
          </span>

          <span className="text-slate-400 flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-[#e5a84b] inline-block" />
            <span>Unobserved future (&gt; T):</span>
            <strong className="text-[#e5a84b] font-semibold">{futureEvents.length} transfer{futureEvents.length !== 1 ? "s" : ""}</strong>
          </span>
        </div>

        <span className="text-[11px] text-slate-400 font-sans">
          Evidence strictly masked at cutoff T to prevent hindsight bias
        </span>
      </div>

      {/* Compact Horizon Strip */}
      <div className="flex gap-2.5 overflow-x-auto pb-1 pt-1">
        {sortedEvents.map((ev, i) => {
          const isHist = new Date(ev.occurred_at).getTime() <= currentDecisionTime;
          const isCurrentDecision = ev.occurred_at === decisionTimestamp;

          return (
            <button
              key={ev.event_id}
              onClick={() => onSelectTimestamp(ev.occurred_at)}
              className={`flex-shrink-0 text-left p-2.5 rounded-xl border text-xs font-sans transition-all cursor-pointer ${
                isCurrentDecision
                  ? "bg-[#17172b] border-[#6666ff] text-white ring-1 ring-[#6666ff]/40 shadow-sm"
                  : isHist
                  ? "bg-[#0c0c16]/70 border-[#23233c] hover:border-[#3b3b5c] text-slate-300"
                  : "bg-[#0c0c16]/40 border-[#1c1c30] opacity-50 hover:opacity-80 text-slate-400"
              }`}
            >
              <div className="flex items-center justify-between gap-2 text-[10px] text-slate-400">
                <span className="font-mono">#{i + 1}</span>
                <span className="font-mono">{ev.occurred_at.slice(11, 16)} UTC</span>
              </div>
              <div className="font-bold font-mono text-slate-100 mt-0.5 truncate max-w-[130px]">
                {formatMinorUnits(ev.amount_minor_units)}
              </div>
              <div className="text-[10px] font-mono text-slate-400 truncate max-w-[130px]">
                {ev.sender.account_id.slice(0, 8)}... &rarr; {ev.receiver.account_id.slice(0, 8)}...
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

