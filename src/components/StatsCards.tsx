/**
 * StatsCards.tsx — Row of quick-stat chips in the expanded view.
 *
 * Shows: cost today · cost this week · most active project
 * Displayed below the plan bars, above the chart.
 */

import React from "react";
import { type SessionStats } from "../lib/api";
import { formatCost, formatDuration } from "../hooks/useSessions";

interface StatsCardsProps {
  stats: SessionStats;
}

interface ChipProps {
  label: string;
  value: string;
  sub?: string;
}

const StatChip: React.FC<ChipProps> = ({ label, value, sub }) => (
  <div className="flex-1 min-w-0 px-3 py-2 rounded-xl bg-white/5 border border-white/8">
    <p className="text-[9px] font-semibold text-gray-500 uppercase tracking-wider leading-none mb-1">
      {label}
    </p>
    <p className="text-sm font-semibold text-gray-200 leading-tight truncate" title={value}>
      {value}
    </p>
    {sub && (
      <p className="text-[10px] text-gray-600 leading-none mt-0.5 truncate">{sub}</p>
    )}
  </div>
);

export const StatsCards: React.FC<StatsCardsProps> = ({ stats }) => {
  return (
    <div className="flex gap-2">
      <StatChip
        label="Today"
        value={formatCost(stats.costToday)}
        sub={`${stats.sessionCount} session${stats.sessionCount === 1 ? "" : "s"} this week`}
      />
      <StatChip
        label="This week"
        value={formatCost(stats.costThisWeek)}
        sub={formatDuration(stats.totalDurationSec)}
      />
      <StatChip
        label="Top project"
        value={stats.mostActiveProject ?? "—"}
      />
    </div>
  );
};
