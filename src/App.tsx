/**
 * App.tsx — Claude Lens floating widget root.
 *
 * Two views:
 *  • Collapsed — 2×2 tile grid (session, weekly, expand, suggest) + optional weekly cost footer
 *  • Expanded  — full-size 2-tile header, stats cards, top project, source breakdown,
 *                daily cost chart, daily duration chart, session list, suggestion footer
 *
 * Drag region: header row (data-tauri-drag-region via onMouseDown).
 * Theme:       solid dark (#0c0c0e) with colored usage tiles.
 */

import React, { useState, useCallback, useEffect } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { LogicalSize } from "@tauri-apps/api/dpi";
import { useUsage }    from "./hooks/useUsage";
import { useSessions, formatCost, totalCostUsd } from "./hooks/useSessions";
import { UsageTile }        from "./components/UsageTile";
import { StaleIndicator }   from "./components/StaleIndicator";
import { SessionList }      from "./components/SessionList";
import { UsageChart }       from "./components/UsageChart";
import { SuggestionBadge }  from "./components/SuggestionBadge";

// ── Icons ─────────────────────────────────────────────────────────────────────

const IconRefresh = () => (
  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M13.5 8A5.5 5.5 0 1 1 10 3.07"/>
    <polyline points="10 1 10 4 13 4"/>
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

const IconBulb = ({ size = 15 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#ffd600" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 21h6"/>
    <path d="M12 3a6 6 0 0 1 6 6c0 2.22-1.2 4.16-3 5.2V17a1 1 0 0 1-1 1H10a1 1 0 0 1-1-1v-2.8C7.2 13.16 6 11.22 6 9a6 6 0 0 1 6-6z"/>
  </svg>
);

// ── Small helpers ─────────────────────────────────────────────────────────────

const Divider = () => <div className="h-px bg-white/[0.08] my-0.5" />;

const SectionTitle = ({ children }: { children: React.ReactNode }) => (
  <p className="font-mono text-[9px] font-bold text-white/75 uppercase tracking-[0.1em] px-3 pt-2 pb-1">
    {children}
  </p>
);

const HeaderButton: React.FC<{
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
  children: React.ReactNode;
}> = ({ onClick, disabled, title, children }) => (
  <button
    onClick={onClick}
    disabled={disabled}
    title={title}
    className="w-[19px] h-[19px] flex items-center justify-center rounded text-[#666] hover:text-white hover:bg-white/[0.08] transition-colors disabled:opacity-40 border-none bg-transparent cursor-pointer"
  >
    {children}
  </button>
);

// ── Source row (expanded breakdown) ──────────────────────────────────────────

interface SourceRowProps {
  label: string;
  dotColor: string;
  share: number;       // 0–1  fraction of local weekly cost
  planPct: number;     // 0–1  weeklyPct × share
  hasData: boolean;    // false when localCostWeek = 0 (costs not yet computed)
  isOverage: boolean;  // suppress plan % when plan is fully consumed
}

const SourceRow: React.FC<SourceRowProps> = ({
  label, dotColor, share, planPct, hasData, isOverage,
}) => (
  <div className="flex items-center justify-between py-[3px]">
    <div className="flex items-center gap-[5px] flex-1 min-w-0">
      <div className={`w-[7px] h-[7px] rounded-full shrink-0 ${dotColor}`} />
      <span className="text-[11px] font-medium text-white truncate">{label}</span>
    </div>
    <div className="text-right shrink-0 ml-3">
      {hasData ? (
        <>
          <div className="font-mono text-[11px] text-white/70 leading-none">
            {Math.round(share * 100)}%
          </div>
          <div className="font-mono text-[9px] text-white/60 mt-[3px] leading-none">
            {isOverage ? "plan maxed" : `${(planPct * 100).toFixed(1)}% of plan`}
          </div>
        </>
      ) : (
        <span className="font-mono text-[10px] text-white/30">—</span>
      )}
    </div>
  </div>
);

// ── Error panel ───────────────────────────────────────────────────────────────

const ErrorPanel: React.FC<{ onRetry: () => void; loading: boolean }> = ({ onRetry, loading }) => (
  <div className="flex flex-col items-center py-[22px] px-3 gap-2 text-center">
    <div className="w-8 h-8 rounded-full bg-danger/10 border border-danger/30 flex items-center justify-center mb-0.5">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ff6b6b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        <circle cx="12" cy="12" r="10"/>
      </svg>
    </div>
    <p className="text-[12px] font-bold text-danger">Cannot reach sidecar</p>
    <p className="font-mono text-[10px] text-white/50 leading-relaxed">
      Make sure Claude Lens<br/>is running
    </p>
    <button
      onClick={onRetry}
      disabled={loading}
      className="font-mono text-[9px] font-bold tracking-[0.06em] text-danger bg-danger/10 border border-danger/25 rounded px-3 py-1 mt-1 cursor-pointer hover:bg-danger/15 transition-colors disabled:opacity-40"
    >
      RETRY →
    </button>
  </div>
);

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

  // Resize window to fit content
  useEffect(() => {
    const win = getCurrentWindow();
    let height: number;
    if (expanded) {
      height = 580;
    } else if (usage?.isStale) {
      height = 296;
    } else {
      height = 264;
    }
    win.setSize(new LogicalSize(340, height)).catch(() => {});
  }, [expanded, usage?.isStale]);

  // Drag from header
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest("button")) return;
    getCurrentWindow().startDragging().catch(() => {});
  }, []);

  // Suggestion count — stub for M5, always 0 until engine is wired
  const suggestionCount = 0;

  const localCostWeek = totalCostUsd(bySource);
  const showBrowserRow = usage !== null && bySource.length > 0 && usage.weeklyPct > 0;

  // Normalise daily cost to % of 7-day total so bars are always visible
  // regardless of absolute cost magnitude (MAX plan users have near-zero USD values).
  // Cowork sessions with unknown model contribute $0 and won't appear in the chart;
  // Code sessions with known models will, even if costs are minimal.
  const dailyPctData = React.useMemo(() => {
    const total = chartData.reduce((sum, pt) => sum + pt.value, 0);
    if (total <= 0) return [];
    return chartData.map(pt => ({ ...pt, value: (pt.value / total) * 100 }));
  }, [chartData]);

  // Logo gradient shifts with the overall warning level
  const logoGradient: Record<typeof level, string> = {
    normal: "from-[#00c6ff] to-[#0072ff]",
    amber:  "from-[#f7971e] to-[#ffd200]",
    danger: "from-[#ff416c] to-[#ff4b2b]",
  };
  const logoBg = (usageLoading && !usage)
    ? "bg-[#222] border border-[#333]"
    : `bg-gradient-to-br ${logoGradient[level]}`;

  // Footer cost color mirrors the overall level
  const footerCostColor: Record<typeof level, string> = {
    normal: "text-primary",
    amber:  "text-amber",
    danger: "text-danger",
  };

  return (
    <div className="min-h-screen flex items-start justify-center p-2 bg-transparent">
      <div className="w-full rounded-[14px] bg-app-bg border border-white/[0.09] shadow-2xl shadow-black/60 overflow-hidden">

        {/* ── Header / drag region ─────────────────────────────────────────── */}
        <div
          onMouseDown={handleDragStart}
          className="flex items-center gap-[7px] px-[11px] py-[9px] border-b border-white/[0.07] cursor-grab active:cursor-grabbing select-none"
        >
          <div className={`w-[19px] h-[19px] rounded-full flex items-center justify-center shrink-0 ${logoBg}`}>
            <span className="font-mono text-[7px] font-bold text-white leading-none">CL</span>
          </div>
          <span className="text-[12px] font-semibold text-white flex-1 tracking-[-0.01em]">
            Claude Lens
          </span>
          {usage?.isStale && (
            <div className="w-[7px] h-[7px] rounded-full bg-[#ffd200] animate-pulse shrink-0" title="Data may be stale" />
          )}
          <HeaderButton onClick={handleRefresh} disabled={usageLoading} title="Force refresh">
            <span className={usageLoading ? "animate-spin inline-block" : ""}><IconRefresh /></span>
          </HeaderButton>
          <HeaderButton onClick={() => setExpanded(v => !v)} title={expanded ? "Collapse" : "Expand"}>
            {expanded ? <IconChevronUp /> : <IconChevronDown />}
          </HeaderButton>
        </div>

        {/* ── Error state (replaces all content) ───────────────────────────── */}
        {usageError && (
          <ErrorPanel onRetry={handleRefresh} loading={usageLoading} />
        )}

        {/* ── Collapsed view ───────────────────────────────────────────────── */}
        {!usageError && !expanded && (
          <>
            {/* 2×2 tile grid */}
            <div className="grid grid-cols-2 gap-[3px] p-[5px] pb-[3px]">
              {usageLoading && !usage ? (
                <>
                  {[0, 1, 2, 3].map((i) => (
                    <div
                      key={i}
                      className="rounded-[9px] min-h-[78px] bg-white/[0.07] animate-pulse"
                      style={{ animationDelay: `${i * 0.1}s` }}
                    />
                  ))}
                </>
              ) : usage ? (
                <>
                  <UsageTile type="session" pct={usage.sessionPct} resetsAt={usage.sessionResetsAt} />
                  <UsageTile type="weekly"  pct={usage.weeklyPct}  resetsAt={usage.weeklyResetsAt} style={{ animationDelay: "0.3s" }} />

                  {/* Expand action tile */}
                  <button
                    onClick={() => setExpanded(true)}
                    className="bg-tile-action border border-white/10 rounded-[9px] min-h-[78px] flex flex-col items-center justify-center gap-[7px] hover:bg-[#1e1e22] transition-colors cursor-pointer"
                  >
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="6 9 12 15 18 9"/>
                    </svg>
                    <span className="font-mono text-[9px] font-semibold uppercase tracking-[0.08em] text-white">
                      Expand
                    </span>
                  </button>

                  {/* Suggest action tile */}
                  <button
                    onClick={() => setExpanded(true)}
                    className={`bg-tile-suggest rounded-[9px] min-h-[78px] flex flex-col items-center justify-center gap-[7px] hover:bg-[#1c1c10] transition-colors cursor-pointer ${
                      suggestionCount > 0
                        ? "border border-[rgba(255,210,0,0.45)]"
                        : "border border-[rgba(255,210,0,0.22)]"
                    }`}
                  >
                    <div className={`w-[30px] h-[30px] rounded-full flex items-center justify-center ${
                      suggestionCount > 0
                        ? "bg-[rgba(255,214,0,0.18)] border-[1.5px] border-[rgba(255,214,0,0.6)]"
                        : "bg-[rgba(255,214,0,0.12)] border-[1.5px] border-[rgba(255,214,0,0.35)]"
                    }`}>
                      <IconBulb size={15} />
                    </div>
                    <span className="font-mono text-[9px] font-semibold uppercase tracking-[0.08em] text-[#ffd600]">
                      {suggestionCount > 0 ? `${suggestionCount} ready` : "Suggest"}
                    </span>
                  </button>
                </>
              ) : null}
            </div>

            {/* Stale banner — collapsed */}
            {usage?.isStale && (
              <StaleIndicator isStale recordedAt={usage.recordedAt} />
            )}

            {/* Footer — weekly cost. Hidden when spend is under $10 to avoid showing
                noise for light usage days; spacing is preserved either way. */}
            {localCostWeek >= 10 ? (
              <div className="px-2.5 pt-[5px] pb-[9px]">
                <div className={`font-mono text-[12px] font-semibold ${footerCostColor[level]}`}>
                  {formatCost(localCostWeek)}
                </div>
                <div className="font-mono text-[9px] text-white/40 uppercase tracking-[0.07em] mt-0.5">
                  this week
                </div>
              </div>
            ) : (
              <div className="pb-[9px]" />
            )}
          </>
        )}

        {/* ── Expanded view ────────────────────────────────────────────────── */}
        {!usageError && expanded && (
          <>
            {/* 1 — Full-size usage tiles */}
            <div className="grid grid-cols-2 gap-[3px] p-[5px] pb-[3px]">
              {usageLoading && !usage ? (
                <>
                  <div className="rounded-[9px] min-h-[78px] bg-white/[0.07] animate-pulse" />
                  <div className="rounded-[9px] min-h-[78px] bg-white/[0.07] animate-pulse" style={{ animationDelay: "0.2s" }} />
                </>
              ) : usage ? (
                <>
                  <UsageTile type="session" pct={usage.sessionPct} resetsAt={usage.sessionResetsAt} />
                  <UsageTile type="weekly"  pct={usage.weeklyPct}  resetsAt={usage.weeklyResetsAt} style={{ animationDelay: "0.3s" }} />
                </>
              ) : null}
            </div>

            {/* Stale banner */}
            {usage?.isStale && (
              <StaleIndicator isStale recordedAt={usage.recordedAt} />
            )}

            <Divider />

            {/* 2 — Top project */}
            {stats?.mostActiveProject && (
              <>
                <div className="px-[10px] py-1">
                  <div className="flex items-center justify-between px-3 py-[7px] rounded-lg bg-white/5 border border-white/10">
                    <span className="font-mono text-[8px] font-bold text-white/75 uppercase tracking-[0.07em] shrink-0 mr-3">
                      Top Project
                    </span>
                    <span className="text-[13px] font-semibold text-white truncate text-right" title={stats.mostActiveProject}>
                      {stats.mostActiveProject}
                    </span>
                  </div>
                </div>
                <Divider />
              </>
            )}

            {/* 4 — 7-day breakdown */}
            <SectionTitle>Last 7 Days</SectionTitle>
            <div className="px-3 pb-[6px]">
              {bySource.length === 0 ? (
                <p className="font-mono text-[10px] text-white/30">No sessions recorded yet.</p>
              ) : (
                <>
                  {bySource.map(s => {
                    const share   = localCostWeek > 0 ? s.totalCostUsd / localCostWeek : 0;
                    const planPct = (usage?.weeklyPct ?? 0) * share;
                    return (
                      <SourceRow
                        key={s.source}
                        label={s.source === "code" ? "Claude Code" : "Cowork"}
                        dotColor={s.source === "code" ? "bg-[#2979ff]" : "bg-[#7c5cbf]"}
                        share={share}
                        planPct={planPct}
                        hasData={localCostWeek > 0}
                        isOverage={(usage?.weeklyPct ?? 0) >= 1.0}
                      />
                    );
                  })}
                  {showBrowserRow && (
                    <div className="flex items-center justify-between py-[3px]">
                      <div className="flex items-center gap-[5px] flex-1 min-w-0">
                        <div className="w-[7px] h-[7px] rounded-full shrink-0 bg-[#444]" />
                        <span className="text-[11px] font-medium text-white/60 truncate">
                          Other (browser)
                        </span>
                      </div>
                      <span className="font-mono text-[9px] text-white/40 italic shrink-0 ml-3">
                        untracked
                      </span>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* 5 — Daily usage chart */}
            {dailyPctData.length > 0 && (
              <>
                <Divider />
                <SectionTitle>Daily Usage</SectionTitle>
                <div className="px-3 pb-1">
                  <UsageChart data={dailyPctData} unit="percent" emptyLabel="No usage data yet." />
                </div>
              </>
            )}

            <Divider />

            {/* 6 — Sessions in the last 7 days */}
            <SectionTitle>
              Sessions in the Last 7 Days{stats ? ` (${stats.sessionCount})` : ""}
            </SectionTitle>
            <div className="px-[10px] pb-[8px]">
              <SessionList sessions={sessions} isLoading={sessionsLoading} />
            </div>

            {/* Suggestion footer */}
            <SuggestionBadge count={suggestionCount} onView={() => {}} />
            {suggestionCount === 0 && <div className="pb-1" />}
          </>
        )}

      </div>
    </div>
  );
}
