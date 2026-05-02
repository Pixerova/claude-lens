/**
 * UsageTile.tsx — Colored tile showing % usage for a single plan meter.
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
  warnAt: number;     // 0–1 fraction, e.g. 0.80
  critAt: number;     // 0–1 fraction, e.g. 0.90
  style?: React.CSSProperties;
}

function alertLevel(pct: number, warnAt: number, critAt: number): AlertLevel {
  if (pct >= critAt) return "danger";
  if (pct >= warnAt) return "amber";
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
  warnAt,
  critAt,
  style,
}) => {
  const level  = alertLevel(pct, warnAt, critAt);
  const isCrit = level === "danger";
  const bg     = BG[type][level];
  const label  = type === "session" ? "Session" : "Weekly";

  // "in 2h 15m" when < 24 h away, "Mon 4:30 AM" otherwise
  const raw        = formatResetTime(resetsAt, true);
  const resetLabel = /^\d/.test(raw) ? `in ${raw}` : raw;

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
