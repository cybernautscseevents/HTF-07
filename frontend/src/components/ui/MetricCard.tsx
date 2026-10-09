import React from "react";
import { StatusBadge, BadgeVariant } from "./StatusBadge";

interface MetricCardProps {
  label: string;
  value: string;
  subvalue?: string;
  badge?: { label: string; variant: BadgeVariant };
  icon?: React.ReactNode;
  accent?: "default" | "emerald" | "amber" | "red" | "cyan";
  className?: string;
  tooltip?: string;
}

export function MetricCard({
  label,
  value,
  subvalue,
  badge,
  icon,
  accent = "default",
  className = "",
  tooltip,
}: MetricCardProps) {
  const accentBorders = {
    default: "border-[#23233c] bg-[#121222] hover:border-[#353555]",
    emerald: "border-[#b9f0d7]/25 bg-[#b9f0d7]/5 hover:border-[#b9f0d7]/40",
    amber: "border-[#e5a84b]/25 bg-[#e5a84b]/5 hover:border-[#e5a84b]/40",
    red: "border-[#e05263]/25 bg-[#e05263]/5 hover:border-[#e05263]/40",
    cyan: "border-[#6666ff]/25 bg-[#6666ff]/5 hover:border-[#6666ff]/40",
  };

  const accentValues = {
    default: "text-slate-100",
    emerald: "text-[#b9f0d7]",
    amber: "text-[#e5a84b]",
    red: "text-[#e05263]",
    cyan: "text-[#c9e8ff]",
  };

  return (
    <div
      title={tooltip}
      className={`rounded-xl border p-4 transition-all duration-150 shadow-sm ${accentBorders[accent]} ${className}`}
    >
      <div className="flex items-center justify-between text-xs font-medium text-slate-400 mb-1.5 font-sans">
        <span className="truncate">{label}</span>
        {icon && <div className="text-slate-500">{icon}</div>}
      </div>

      <div className="flex items-baseline justify-between gap-2 mt-1">
        <div className={`text-xl font-bold tracking-tight font-mono ${accentValues[accent]}`}>
          {value}
        </div>
        {badge && <StatusBadge label={badge.label} variant={badge.variant} size="sm" />}
      </div>

      {subvalue && (
        <div className="text-[11px] text-slate-400 mt-1.5 truncate font-sans">
          {subvalue}
        </div>
      )}
    </div>
  );
}
