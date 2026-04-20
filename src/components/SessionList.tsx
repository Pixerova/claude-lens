/**
 * SessionList.tsx — Scrollable list of recent sessions.
 *
 * Each row: % of weekly plan · source badge · project / conversation label
 * Order: most recent first.
 *
 * Cowork sessions use the conversation title when available, falling back
 * to a formatted timestamp. Cost column removed — not meaningful on MAX plan.
 */

import React from "react";
import { type Session } from "../lib/api";

interface SessionListProps {
  sessions: Session[];
  isLoading: boolean;
}

/** Format a cowork session as "Apr 14 · 3:30 PM". */
function coworkLabel(startedAt: string): string {
  const d = new Date(startedAt);
  const date = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  return `${date} · ${time}`;
}

function SourceBadge({ source }: { source: "code" | "cowork" }) {
  const isCode = source === "code";
  return (
    <span
      className={`inline-flex items-center font-mono text-[8px] font-bold tracking-[0.04em] uppercase px-[4px] py-[1px] rounded-[3px] leading-none shrink-0 ${
        isCode
          ? "bg-[rgba(41,121,255,0.2)] text-[#6eb0ff]"
          : "bg-[rgba(124,92,191,0.2)] text-[#b89ef0]"
      }`}
    >
      {isCode ? "Code" : "Cowork"}
    </span>
  );
}

export const SessionList: React.FC<SessionListProps> = ({ sessions, isLoading }) => {
  if (isLoading) {
    return (
      <div className="space-y-[4px] mt-1">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-[16px] rounded-[4px] bg-white/[0.07] animate-pulse" style={{ animationDelay: `${i * 0.08}s` }} />
        ))}
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <p className="font-mono text-[10px] text-white/60 text-center py-3">
        No sessions in the last 7 days.
      </p>
    );
  }

  return (
    <div
      className="max-h-[168px] overflow-y-auto"
      style={{ scrollbarWidth: "thin", scrollbarColor: "#333 transparent" }}
    >
      {/* Column headers */}
      <div className="flex items-center gap-[5px] px-[4px] pb-[4px]">
        <span className="font-mono text-[8px] font-bold text-white/60 uppercase tracking-[0.06em] w-[24px] text-right shrink-0">%</span>
        <span className="font-mono text-[8px] font-bold text-white/60 uppercase tracking-[0.06em] w-[46px] shrink-0">Src</span>
        <span className="font-mono text-[8px] font-bold text-white/60 uppercase tracking-[0.06em] flex-1 min-w-0">Session</span>
      </div>

      {sessions.map((s) => {
        // Cowork: conversation title when available, otherwise formatted timestamp.
        const label = s.source === "cowork"
          ? (s.title ?? coworkLabel(s.startedAt))
          : null;

        const pct = s.pctOfWeek < 0.005
          ? "< 1%"
          : `${Math.round(s.pctOfWeek * 100)}%`;

        return (
          <div
            key={s.sessionId}
            className="flex items-center gap-[5px] px-[4px] py-[2px] rounded-[4px] hover:bg-white/[0.04] transition-colors"
          >
            <span className="font-mono text-[9px] text-white/65 tabular-nums w-[24px] text-right shrink-0 leading-none">
              {pct}
            </span>
            <div className="w-[46px] shrink-0 flex items-center">
              <SourceBadge source={s.source} />
            </div>
            {s.source === "code" ? (
              <span
                className="flex-1 min-w-0 text-[10px] font-medium text-white truncate leading-none"
                title={[s.project, s.title].filter(Boolean).join(" : ") || s.model || s.source}
              >
                {s.project && (
                  <span className="text-[#6eb0ff]">{s.project}</span>
                )}
                {s.project && s.title && " : "}
                {s.title ?? (!s.project ? (s.model ?? s.source) : null)}
              </span>
            ) : (
              <span
                className="flex-1 min-w-0 text-[10px] font-medium text-white truncate leading-none"
                title={label ?? undefined}
              >
                {label}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
};
