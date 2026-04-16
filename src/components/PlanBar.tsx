/**
 * PlanBar.tsx — Horizontal usage bar with label, percentage, and reset time.
 *
 * Color logic:
 *   < 80%  → primary blue
 *   80-89% → amber
 *   ≥ 90%  → danger red
 */

import React from "react";
import { formatPct, formatResetTime } from "../hooks/useUsage";

interface PlanBarProps {
  label: string;          // "Session" | "Weekly"
  pct: number;            // 0–1
  resetsAt: string;       // ISO 8601
  short?: boolean;        // compact mode — shorter reset string
}

function barColor(pct: number): string {
  if (pct >= 0.90) return "bg-danger";
  if (pct >= 0.80) return "bg-amber";
  return "bg-primary";
}

function textColor(pct: number): string {
  if (pct >= 0.90) return "text-danger";
  if (pct >= 0.80) return "text-amber";
  return "text-primary";
}

export const PlanBar: React.FC<PlanBarProps> = ({ label, pct, resetsAt, short = false }) => {
  const clampedPct = Math.min(1, Math.max(0, pct));
  const widthPct   = `${Math.round(clampedPct * 100)}%`;

  return (
    <div className="mb-3 last:mb-0">
      {/* Label row */}
      <div className="flex justify-between items-baseline mb-1">
        <span className="text-xs text-gray-400 font-medium tracking-wide uppercase">
          {label}
        </span>
        <span className={`text-xs font-semibold ${textColor(clampedPct)}`}>
          {formatPct(clampedPct)}
        </span>
      </div>

      {/* Bar track */}
      <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${barColor(clampedPct)}`}
          style={{ width: widthPct }}
        />
      </div>

      {/* Reset time */}
      {resetsAt && (
        <p className="mt-1 text-[10px] text-gray-500 leading-none">
          {formatResetTime(resetsAt, short)}
        </p>
      )}
    </div>
  );
};
