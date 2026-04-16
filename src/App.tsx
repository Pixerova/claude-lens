/**
 * App.tsx — Claude Lens floating widget root.
 *
 * Two views:
 *  • Compact  — plan bars + stale dot + suggestion badge + expand toggle
 *  • Expanded — plan bars, stats cards, source breakdown (+ browser note),
 *               cost chart, session list
 *
 * Drag region: data-tauri-drag-region on the header row.
 * Theme:       dark glass (bg-surface/85 backdrop-blur-xl).
 */

import React, { useState, useCallback, useEffect } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { LogicalSize } from "@tauri-apps/api/dpi";
import { useUsage }    from "./hooks/useUsage";
import { useSessions, formatCost, totalCostUsd } from "./hooks/useSessions";
import { PlanBar }          from "./components/PlanBar";
import { StaleIndicator }   from "./components/StaleIndicator";
import { SessionList }      from "./components/SessionList";
import { UsageChart }       from "./components/UsageChart";
import { StatsCards }       from "./components/StatsCards";
import { SuggestionBadge }  from "./components/SuggestionBadge";

// ── Icons ─────────────────────────────────────────────────────────────────────

const IconRefresh = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 2v6h-6"/>
    <path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
    <path d="M3 22v-6h6"/>
    <path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
  </svg>
);

const IconChevronDown = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 9l6 6 6-6"/>
  </svg>
);

const IconChevronUp = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 15l-6-6-6 6"/>
  </svg>
);

// ── Small helpers ─────────────────────────────────────────────────────────────

const Divider = () => <div className="h-px bg-white/8 my-3" />;

const RefreshButton: React.FC<{ onClick: () => void; loading: boolean }> = ({ onClick, loading }) => (
  <button
    onClick={onClick}
    disabled={loading}
    className="p-1.5 rounded-md text-gray-500 hover:text-gray-300 hover:bg-white/8 transition-colors disabled:opacity-40"
    title="Force refresh"
  >
    <span className={loading ? "animate-spin inline-block" : ""}><IconRefresh /></span>
  </button>
);

// ── Source row (breakdown by code/cowork/browser) ─────────────────────────────

interface SourceRowProps {
  label: string;
  count?: number;
  durationSec?: number;
  costUsd: number;
  muted?: boolean;      // browser row uses muted style
}

const SourceRow: React.FC<SourceRowProps> = ({ label, count, durationSec, costUsd, muted }) => {
  const hrs  = durationSec ? Math.floor(durationSec / 3600) : 0;
  const mins = durationSec ? Math.floor((durationSec % 3600) / 60) : 0;
  const dur  = durationSec
    ? (hrs > 0 ? `${hrs}h ${mins}m` : `${mins}m`)
    : null;

  return (
    <div className={`flex justify-between items-center text-xs ${muted ? "opacity-60" : ""}`}>
      <span className="text-gray-400">
        {label}
        {count !== undefined && (
          <span className="text-gray-600 ml-1">({count})</span>
        )}
      </span>
      <div className="flex gap-3 text-gray-500 items-center">
        {dur && <span>{dur}</span>}
        <span className={`font-medium ${muted ? "text-gray-500" : "text-gray-400"}`}>
          {muted ? "untracked" : formatCost(costUsd)}
        </span>
      </div>
    </div>
  );
};

// ── Main ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [expanded, setExpanded] = useState(false);

  const {
    usage,
    level,
    isLoading: usageLoading,
    error: usageError,
    refresh: refreshUsage,
  } = useUsage();

  const {
    sessions,
    stats,
    bySource,
    chartData,
    isLoading: sessionsLoading,
    refresh: refreshSessions,
  } = useSessions();

  const handleRefresh = useCallback(async () => {
    await Promise.all([refreshUsage(), refreshSessions()]);
  }, [refreshUsage, refreshSessions]);

  // Resize window to match collapsed/expanded content
  useEffect(() => {
    const win = getCurrentWindow();
    const height = expanded ? 520 : 200;
    win.setSize(new LogicalSize(340, height)).catch(() => {});
  }, [expanded]);

  // Drag from header
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest("button")) return;
    getCurrentWindow().startDragging().catch(() => {});
  }, []);

  // Suggestion count — stub for M5, always 0 until engine is wired
  const suggestionCount = 0;

  // Border accent based on warning level
  const borderAccent =
    level === "danger" ? "border-danger/40" :
    level === "amber"  ? "border-amber/40"  :
    "border-white/10";

  // "Other (browser)" — visible only when we have OAuth data and local sessions
  const localCostWeek = totalCostUsd(bySource);
  const showBrowserRow =
    usage !== null &&
    bySource.length > 0 &&
    usage.weeklyPct > 0;

  return (
    <div className="min-h-screen flex items-start justify-center p-2 bg-transparent">
      <div
        className={`
          w-full rounded-2xl
          bg-surface/85 backdrop-blur-xl
          border ${borderAccent}
          shadow-2xl shadow-black/50
          transition-all duration-300 ease-in-out
          overflow-hidden
        `}
      >
        {/* ── Header / drag region ── */}
        <div
          onMouseDown={handleDragStart}
          className="flex items-center justify-between px-4 pt-4 pb-2 cursor-grab active:cursor-grabbing select-none"
        >
          <div className="flex items-center gap-2">
            <div className="w-5 h-5 rounded-full bg-gradient-to-br from-primary to-blue-600 flex items-center justify-center shrink-0">
              <span className="text-[9px] font-bold text-white leading-none">CL</span>
            </div>
            <span className="text-sm font-semibold text-gray-200 tracking-tight">
              Claude Lens
            </span>
            {usage?.isStale && (
              <div className="w-1.5 h-1.5 rounded-full bg-amber animate-pulse" title="Data may be stale" />
            )}
          </div>

          <div className="flex items-center gap-1">
            <RefreshButton onClick={handleRefresh} loading={usageLoading} />
            <button
              onClick={() => setExpanded(v => !v)}
              className="p-1.5 rounded-md text-gray-500 hover:text-gray-300 hover:bg-white/8 transition-colors"
              title={expanded ? "Collapse" : "Expand"}
            >
              {expanded ? <IconChevronUp /> : <IconChevronDown />}
            </button>
          </div>
        </div>

        {/* ── Plan bars ── */}
        <div className="px-4 pb-2">
          {usageError ? (
            <div className="py-3 text-center">
              <p className="text-xs text-danger">Cannot reach sidecar</p>
              <p className="text-[10px] text-gray-600 mt-0.5">Make sure Claude Lens is running</p>
            </div>
          ) : usageLoading && !usage ? (
            <div className="space-y-3">
              <div className="h-8 rounded-lg bg-white/5 animate-pulse" />
              <div className="h-8 rounded-lg bg-white/5 animate-pulse" />
            </div>
          ) : usage ? (
            <>
              <PlanBar
                label="Session"
                pct={usage.sessionPct}
                resetsAt={usage.sessionResetsAt}
                short={!expanded}
              />
              <PlanBar
                label="Weekly"
                pct={usage.weeklyPct}
                resetsAt={usage.weeklyResetsAt}
                short={!expanded}
              />
              {usage.isStale && (
                <div className="mt-2">
                  <StaleIndicator isStale={usage.isStale} recordedAt={usage.recordedAt} />
                </div>
              )}
            </>
          ) : null}
        </div>

        {/* ── Compact footer ── */}
        {!expanded && (
          <>
            {localCostWeek > 0 && (
              <div className="px-4 pb-2 flex justify-between items-center">
                <span className="text-[10px] text-gray-600">
                  {formatCost(localCostWeek)} tracked this week
                </span>
                <span className="text-[10px] text-gray-600">
                  {sessions.length > 0
                    ? `${sessions.length} session${sessions.length === 1 ? "" : "s"}`
                    : ""}
                </span>
              </div>
            )}
            <SuggestionBadge
              count={suggestionCount}
              onView={() => setExpanded(true)}
            />
            {/* Bottom padding when no suggestion badge */}
            {suggestionCount === 0 && <div className="pb-2" />}
          </>
        )}

        {/* ── Expanded panel ── */}
        {expanded && (
          <>
            {/* Stats cards */}
            {stats && (
              <>
                <Divider />
                <div className="px-4">
                  <StatsCards stats={stats} />
                </div>
              </>
            )}

            <Divider />

            {/* Source breakdown */}
            <div className="px-4 space-y-1.5">
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">
                7-day breakdown
              </p>
              {bySource.length === 0 ? (
                <p className="text-xs text-gray-600">No sessions recorded yet.</p>
              ) : (
                <>
                  {bySource.map(s => (
                    <SourceRow
                      key={s.source}
                      label={s.source === "code" ? "Claude Code" : "Cowork"}
                      count={s.sessionCount}
                      durationSec={s.totalDurationSec}
                      costUsd={s.totalCostUsd}
                    />
                  ))}

                  {/* Other (incl. browser) — always shown to indicate gap */}
                  {showBrowserRow && (
                    <SourceRow
                      label="Other (incl. browser)"
                      costUsd={0}
                      muted
                    />
                  )}

                  {/* Total */}
                  {bySource.length > 0 && (
                    <div className="flex justify-between items-center text-xs pt-1.5 border-t border-white/8">
                      <span className="text-gray-500">Tracked total</span>
                      <span className="text-gray-300 font-semibold">
                        {formatCost(localCostWeek)}
                      </span>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Cost chart */}
            {chartData.length > 0 && (
              <>
                <div className="px-4 mt-4">
                  <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">
                    Daily cost
                  </p>
                  <UsageChart data={chartData} />
                </div>
              </>
            )}

            <Divider />

            {/* Session list */}
            <div className="px-4 pb-4">
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">
                Recent sessions
              </p>
              <SessionList sessions={sessions} isLoading={sessionsLoading} />
            </div>

            {/* Suggestion badge at bottom of expanded view too */}
            <SuggestionBadge
              count={suggestionCount}
              onView={() => {}}   // already expanded — will scroll to suggestions in M5
            />
            {suggestionCount === 0 && <div className="pb-1" />}
          </>
        )}
      </div>
    </div>
  );
}
