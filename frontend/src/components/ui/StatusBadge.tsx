import React from "react";

export type BadgeVariant =
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "neutral"
  | "purple";

interface StatusBadgeProps {
  label: string;
  variant?: BadgeVariant;
  size?: "sm" | "md";
  dot?: boolean;
  className?: string;
}

export function StatusBadge({
  label,
  variant = "neutral",
  size = "md",
  dot = true,
  className = "",
}: StatusBadgeProps) {
  const variantStyles: Record<
    BadgeVariant,
    { bg: string; text: string; dotColor: string; border: string }
  > = {
    success: {
      bg: "bg-[#b9f0d7]/10",
      text: "text-[#b9f0d7]",
      dotColor: "bg-[#b9f0d7]",
      border: "border-[#b9f0d7]/30",
    },
    warning: {
      bg: "bg-[#e5a84b]/10",
      text: "text-[#e5a84b]",
      dotColor: "bg-[#e5a84b]",
      border: "border-[#e5a84b]/30",
    },
    danger: {
      bg: "bg-[#e05263]/10",
      text: "text-[#e05263]",
      dotColor: "bg-[#e05263]",
      border: "border-[#e05263]/30",
    },
    info: {
      bg: "bg-[#c9e8ff]/10",
      text: "text-[#c9e8ff]",
      dotColor: "bg-[#c9e8ff]",
      border: "border-[#c9e8ff]/30",
    },
    purple: {
      bg: "bg-[#6666ff]/10",
      text: "text-[#b0baff]",
      dotColor: "bg-[#6666ff]",
      border: "border-[#6666ff]/30",
    },
    neutral: {
      bg: "bg-[#17172b]",
      text: "text-slate-300",
      dotColor: "bg-slate-400",
      border: "border-[#23233c]",
    },
  };

  const style = variantStyles[variant];
  const sizeStyles =
    size === "sm"
      ? "text-[11px] px-2.5 py-0.5 gap-1.5"
      : "text-xs px-3 py-1 gap-2";

  return (
    <span
      className={`inline-flex items-center font-medium font-sans rounded-full border ${style.bg} ${style.text} ${style.border} ${sizeStyles} ${className}`}
    >
      {dot && (
        <span
          className={`h-1.5 w-1.5 rounded-full ${style.dotColor} shrink-0`}
        />
      )}
      <span className="truncate">{label}</span>
    </span>
  );
}
