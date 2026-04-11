/**
 * SessionList.tsx — Scrollable list of recent sessions.
 *
 * Each row: % of week's tracked cost · source badge · project/model · duration · cost · relative time
 * Order: most recent first.
 */

import React from "react";
import { type Session } from "../lib/api";
import { formatDuration, formatCost } from "../hooks/useSessions";

interface SessionListProps {
  sessions: Session[];
  isLoading: boolean;
}

function SourceBadge({ source }: { source: "code" | "cowork" }) {
  const isCode = source === "code";
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-semibold tracking-wide uppercase leading-none shrink-0 ${
        isCode
          ? "bg-primary/20 text-primary"
          : "bg-purple-500/20 text-purple-400"
      }`}
    >
      {isCode ? "Code" : "Cowork"}
    </span>
  );
}

function relativeDate(isoString: string): string {
  const d    = new Date(isoString);
  const now  = new Date();
  const diff = now.getTime() - d.getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1)   return "just now";
  if (mins < 60)  return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)   return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function PctPill({ pct }: { pct: number }) {
  const display = pct < 0.005 ? "< 1%" : `${Math.round(pct * 100)}%`;
  return (
    <span className="w-9 shrink-0 text-right text-[10px] font-semibold text-gray-400 tabular-nums">
      {display}
    </span>
  );
}

export const SessionList: React.FC<SessionListProps> = ({ sessions, isLoading }) => {
  if (isLoading) {
    return (
      <div className="space-y-2 mt-2">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-10 rounded-lg bg-white/5 animate-pulse" />
        ))}
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <p className="mt-4 text-center text-xs text-gray-500">
        No sessions found in the last 7 days.
      </p>
    );
  }

  return (
    <div className="mt-1 space-y-1 max-h-52 overflow-y-auto pr-1">
      {/* Column headers */}
      <div className="flex items-center gap-2 px-2.5 mb-0.5">
        <span className="w-9 shrink-0 text-right text-[9px] text-gray-600 uppercase tracking-wide">%</span>
        <span className="flex-1 text-[9px] text-gray-600 uppercase tracking-wide">Project</span>
        <span className="text-[9px] text-gray-600 uppercase tracking-wide shrink-0">Duration</span>
        <span className="text-[9px] text-gray-600 uppercase tracking-wide shrink-0 w-12 text-right">Cost</span>
      </div>

      {sessions.map((s) => {
        const label = s.project ?? s.model ?? s.source;
        return (
          <div
            key={s.sessionId}
            className="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-white/5 hover:bg-white/8 transition-colors"
          >
            <PctPill pct={s.pctOfWeek} />
            <SourceBadge source={s.source} />

            {/* Project / model label */}
            <span
              className="flex-1 min-w-0 text-xs text-gray-300 truncate"
              title={label ?? undefined}
            >
              {label}
            </span>

            {/* Stats */}
            <span className="text-[10px] text-gray-400 shrink-0">
              {formatDuration(s.durationSec)}
            </span>
            <span className="text-[10px] text-gray-500 shrink-0 w-12 text-right tabular-nums">
              {formatCost(s.costUsd)}
            </span>
          </div>
        );
      })}
    </div>
  );
};
