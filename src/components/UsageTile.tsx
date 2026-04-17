/**
 * UsageTile.tsx — Colored tile showing % usage for a single plan meter.
 *
 * Used in two sizes:
 *   full    — collapsed view (min-height 78px, 34px number)
 *   compact — expanded view header (min-height 58px, 24px number)
 *
 * Background color encodes both the meter type (session vs weekly)
 * and the current alert level (normal / warn / crit).
 * Critical tiles pulse via the `animate-flash` utility.
 */

import React from "react";
import { formatResetTime, formatPct } from "../hooks/useUsage";

type MeterType = "session" | "weekly";
type AlertLevel = "normal" | "amber" | "danger";

interface UsageTileProps {
  type: MeterType;
  pct: number;        // 0–1
  resetsAt: string;   // ISO 8601
  compact?: boolean;
  style?: React.CSSProperties;
}

function alertLevel(pct: number): AlertLevel {
  if (pct >= 0.90) return "danger";
  if (pct >= 0.80) return "amber";
  return "normal";
}

// Complete class strings — must be literals so Tailwind includes them in the build
const BG: Record<MeterType, Record<AlertLevel, string>> = {
  session: {
    normal: "bg-tile-sess-norm",
    amber:  "bg-tile-sess-warn",
    danger: "bg-tile-sess-crit",
  },
  weekly: {
    normal: "bg-tile-week-norm",
    amber:  "bg-tile-week-warn",
    danger: "bg-tile-week-crit",
  },
};

export const UsageTile: React.FC<UsageTileProps> = ({
  type,
  pct,
  resetsAt,
  compact = false,
  style,
}) => {
  const level  = alertLevel(pct);
  const isCrit = level === "danger";
  const bg     = BG[type][level];
  const label  = type === "session" ? "Session" : "Weekly";

  // "in 2h 15m" when < 24 h away, "Mon 4:30 AM" otherwise
  const raw        = formatResetTime(resetsAt, true);
  const resetLabel = /^\d/.test(raw) ? `in ${raw}` : raw;

  if (compact) {
    return (
      <div
        className={`${bg} rounded-[9px] px-2.5 py-2 flex flex-col justify-between min-h-[58px] overflow-hidden${isCrit ? " animate-flash" : ""}`}
        style={style}
      >
        <div className="font-mono text-2xl font-bold tracking-tighter leading-none text-white">
          {formatPct(pct)}
        </div>
        <div>
          <div className="font-mono text-[9px] font-semibold uppercase tracking-[0.09em] text-white/75 mt-1">
            {label}
          </div>
          <div className="font-mono text-[9px] text-white/55 mt-0.5">
            {resetLabel}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`${bg} rounded-[9px] px-2.5 py-[11px] flex flex-col justify-between min-h-[78px] overflow-hidden${isCrit ? " animate-flash" : ""}`}
      style={style}
    >
      <div className="font-mono text-[34px] font-bold tracking-[-0.04em] leading-none text-white">
        {formatPct(pct)}
      </div>
      <div>
        <div className="font-mono text-[9px] font-semibold uppercase tracking-[0.09em] text-white/75 mt-1">
          {label}
        </div>
        <div className="font-mono text-[9px] text-white/55 mt-0.5">
          {resetLabel}
        </div>
      </div>
    </div>
  );
};
