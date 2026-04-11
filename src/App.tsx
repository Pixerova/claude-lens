/**
 * App.tsx — Claude Lens floating widget root.
 *
 * Two views:
 *  • Compact  — always-visible strip: plan bars + stale dot + expand button
 *  • Expanded — full panel: plan bars, session list, cost chart, refresh button
 *
 * Drag region:  data-tauri-drag-region on the header row.
 * Theme:        dark glass (bg-surface/80 backdrop-blur).
 */

import React, { useState, useCallback } from "react";
import { useUsage }    from "./hooks/useUsage";
import { useSessions, formatCost, totalCostUsd } from "./hooks/useSessions";
import { PlanBar }        from "./components/PlanBar";
import { StaleIndicator } from "./components/StaleIndicator";
import { SessionList }    from "./components/SessionList";
import { UsageChart }     from "./components/UsageChart";

// ── Icons (inline SVG to avoid extra deps) ────────────────────────────────────

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

// ── Divider ───────────────────────────────────────────────────────────────────

const Divider = () => <div className="h-px bg-white/8 my-3" />;

// ── Spinning refresh ──────────────────────────────────────────────────────────

interface RefreshButtonProps {
  onClick: () => void;
  loading: boolean;
}

const RefreshButton: React.FC<RefreshButtonProps> = ({ onClick, loading }) => (
  <button
    onClick={onClick}
    disabled={loading}
    className="p-1.5 rounded-md text-gray-500 hover:text-gray-300 hover:bg-white/8 transition-colors disabled:opacity-40"
    title="Force refresh"
  >
    <span className={loading ? "animate-spin inline-block" : ""}>
      <IconRefresh />
    </span>
  </button>
);

// ── Source breakdown row ──────────────────────────────────────────────────────

interface SourceRowProps {
  label: string;
  count: number;
  durationSec: number;
  costUsd: number;
}

const SourceRow: React.FC<SourceRowProps> = ({ label, count, durationSec, costUsd }) => {
  const hrs  = Math.floor(durationSec / 3600);
  const mins = Math.floor((durationSec % 3600) / 60);
  const dur  = hrs > 0 ? `${hrs}h ${mins}m` : `${mins}m`;

  return (
    <div className="flex justify-between items-center text-xs">
      <span className="text-gray-400">
        {label}
        <span className="text-gray-600 ml-1">({count})</span>
      </span>
      <div className="flex gap-3 text-gray-500">
        <span>{dur}</span>
        <span className="text-gray-400 font-medium">{formatCost(costUsd)}</span>
      </div>
    </div>
  );
};

// ── Main App ──────────────────────────────────────────────────────────────────

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
    bySource,
    chartData,
    isLoading: sessionsLoading,
    refresh: refreshSessions,
  } = useSessions();

  const handleRefresh = useCallback(async () => {
    await Promise.all([refreshUsage(), refreshSessions()]);
  }, [refreshUsage, refreshSessions]);

  // Border accent colour based on plan level
  const borderAccent =
    level === "danger" ? "border-danger/40" :
    level === "amber"  ? "border-amber/40"  :
    "border-white/10";

  return (
    <div
      className={`
        min-h-screen flex items-start justify-center p-2
        bg-transparent
      `}
    >
      <div
        className={`
          w-full max-w-[320px] rounded-2xl
          bg-surface/85 backdrop-blur-xl
          border ${borderAccent}
          shadow-2xl shadow-black/50
          transition-all duration-300 ease-in-out
          overflow-hidden
        `}
      >
        {/* ── Header / drag region ── */}
        <div
          data-tauri-drag-region
          className="flex items-center justify-between px-4 pt-4 pb-2 cursor-grab active:cursor-grabbing select-none"
        >
          {/* Logo + title */}
          <div className="flex items-center gap-2" data-tauri-drag-region>
            <div className="w-5 h-5 rounded-full bg-gradient-to-br from-primary to-blue-600 flex items-center justify-center shrink-0">
              <span className="text-[9px] font-bold text-white leading-none">CL</span>
            </div>
            <span className="text-sm font-semibold text-gray-200 tracking-tight" data-tauri-drag-region>
              Claude Lens
            </span>
            {usage?.isStale && (
              <div className="w-1.5 h-1.5 rounded-full bg-amber animate-pulse" title="Data may be stale" />
            )}
          </div>

          {/* Controls */}
          <div className="flex items-center gap-1">
            <RefreshButton onClick={handleRefresh} loading={usageLoading} />
            <button
              onClick={() => setExpanded((v) => !v)}
              className="p-1.5 rounded-md text-gray-500 hover:text-gray-300 hover:bg-white/8 transition-colors"
              title={expanded ? "Collapse" : "Expand"}
            >
              {expanded ? <IconChevronUp /> : <IconChevronDown />}
            </button>
          </div>
        </div>

        {/* ── Plan bars ── */}
        <div className="px-4 pb-3">
          {usageError ? (
            <div className="py-3 text-center">
              <p className="text-xs text-danger">Cannot reach sidecar</p>
              <p className="text-[10px] text-gray-600 mt-0.5">
                Make sure Claude Lens is running
              </p>
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
                  <StaleIndicator
                    isStale={usage.isStale}
                    recordedAt={usage.recordedAt}
                    error={usageError}
                  />
                </div>
              )}
            </>
          ) : null}
        </div>

        {/* ── Expanded panel ── */}
        {expanded && (
          <>
            <Divider />

            {/* Cost breakdown by source */}
            <div className="px-4 space-y-1.5">
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">
                7-day breakdown
              </p>
              {bySource.length === 0 ? (
                <p className="text-xs text-gray-600">No sessions recorded yet.</p>
              ) : (
                <>
                  {bySource.map((s) => (
                    <SourceRow
                      key={s.source}
                      label={s.source === "code" ? "Claude Code" : "Cowork"}
                      count={s.sessionCount}
                      durationSec={s.totalDurationSec}
                      costUsd={s.totalCostUsd}
                    />
                  ))}
                  {bySource.length > 1 && (
                    <div className="flex justify-between items-center text-xs pt-1 border-t border-white/8">
                      <span className="text-gray-500">Total</span>
                      <span className="text-gray-300 font-semibold">
                        {formatCost(totalCostUsd(bySource))}
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

            {/* Recent sessions */}
            <div className="px-4 pb-4">
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">
                Recent sessions
              </p>
              <SessionList sessions={sessions} isLoading={sessionsLoading} />
            </div>
          </>
        )}

        {/* ── Compact footer (collapsed only) ── */}
        {!expanded && (
          <div className="px-4 pb-3 flex justify-between items-center">
            {bySource.length > 0 ? (
              <span className="text-[10px] text-gray-600">
                {formatCost(totalCostUsd(bySource))} this week
              </span>
            ) : (
              <span />
            )}
            <span className="text-[10px] text-gray-600">
              {sessions.length > 0
                ? `${sessions.length} session${sessions.length === 1 ? "" : "s"}`
                : ""}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
