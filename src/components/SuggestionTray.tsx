import React, { useState, useCallback } from "react";
import { Suggestion, UsageCurrent } from "../lib/api";
import { SuggestionCard } from "./SuggestionCard";
import { UsageTile } from "./UsageTile";

interface SuggestionTrayProps {
  suggestions: Suggestion[];
  usage: UsageCurrent;
  onBack: () => void;
}

export const SuggestionTray: React.FC<SuggestionTrayProps> = ({ suggestions, usage, onBack }) => {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set());
  const [fadingIds, setFadingIds] = useState<Set<string>>(new Set());

  const activeCards = suggestions.filter(s => !dismissedIds.has(s.id));
  const total = suggestions.length;

  const handleToggle = useCallback((id: string) => {
    setExpandedId(prev => (prev === id ? null : id));
  }, []);

  const handleDismissed = useCallback((id: string) => {
    setFadingIds(prev => new Set(prev).add(id));
    setTimeout(() => {
      setDismissedIds(prev => new Set(prev).add(id));
      setFadingIds(prev => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }, 200);
  }, []);

  return (
    <div className="flex flex-col" style={{ flex: 1, minHeight: 0 }}>
      {/* Stat tiles — same as expanded view */}
      <div className="grid grid-cols-2 gap-[3px] p-[5px] pb-[3px]">
        <UsageTile type="session" pct={usage.sessionPct} resetsAt={usage.sessionResetsAt} />
        <UsageTile type="weekly"  pct={usage.weeklyPct}  resetsAt={usage.weeklyResetsAt} style={{ animationDelay: "0.3s" }} />
      </div>

      {/* Tray header */}
      <div
        className="flex items-center justify-between px-[14px] shrink-0"
        style={{
          height: "34px",
          paddingTop: "10px",
          paddingBottom: "8px",
          borderBottom: "1px solid #1e1e1e",
        }}
      >
        <button
          onClick={onBack}
          className="font-mono font-bold uppercase tracking-[0.1em] transition-colors"
          style={{
            fontSize: "11px",
            background: "#f5c200",
            color: "#000",
            border: "none",
            borderRadius: "4px",
            padding: "5px 10px",
            cursor: "pointer",
          }}
          onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "#ffe033"}
          onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "#f5c200"}
        >
          ← Stats
        </button>
        <span
          className="font-mono tracking-[0.08em]"
          style={{ fontSize: "11px", color: "#888" }}
        >
          {activeCards.length}/{total} ACTIVE
        </span>
      </div>

      {/* Card list */}
      <div className="overflow-y-auto" style={{ maxHeight: "400px" }}>
        {activeCards.length === 0 ? (
          <div
            className="flex flex-col items-center justify-center px-[14px] py-[40px]"
            style={{ gap: "6px" }}
          >
            <p
              className="font-mono font-bold uppercase tracking-[0.1em] text-center"
              style={{ fontSize: "11px", color: "#555" }}
            >
              All suggestions dismissed
            </p>
            <p
              className="font-mono text-center"
              style={{ fontSize: "11px", color: "#444" }}
            >
              Check back after your next session.
            </p>
          </div>
        ) : (
          activeCards.map(s => (
            <div
              key={s.id}
              style={{
                transition: "opacity 0.2s",
                opacity: fadingIds.has(s.id) ? 0 : 1,
              }}
            >
              <SuggestionCard
                suggestion={s}
                isExpanded={expandedId === s.id}
                onToggle={() => handleToggle(s.id)}
                onDismissed={handleDismissed}
              />
            </div>
          ))
        )}
      </div>
    </div>
  );
};
