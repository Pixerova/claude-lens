/**
 * App.tsx — claude-lens floating widget root.
 *
 * Two views:
 *  • Collapsed — 2×2 tile grid (session, weekly, expand, suggest)
 *  • Expanded  — full-size 2-tile header, stats cards, top project, source breakdown,
 *                daily cost chart, session list, suggestion footer
 *
 * Drag region: header row (data-tauri-drag-region via onMouseDown).
 * Theme:       solid dark (#0c0c0e) with colored usage tiles.
 */

import React, { useState, useCallback, useEffect } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { LogicalSize } from "@tauri-apps/api/dpi";
import { useUsage }    from "./hooks/useUsage";
import { useSessions, totalCostUsd } from "./hooks/useSessions";
import { useSuggestions } from "./hooks/useSuggestions";
import { UsageTile }        from "./components/UsageTile";
import { StaleIndicator }   from "./components/StaleIndicator";
import { SleepIndicator }   from "./components/SleepIndicator";
import { SessionList }      from "./components/SessionList";
import { UsageChart }       from "./components/UsageChart";
import { SuggestionBadge }  from "./components/SuggestionBadge";
import { SuggestionTray }   from "./components/SuggestionTray";
import Onboarding           from "./components/Onboarding";
import { api }              from "./lib/api";

// ── Icons ─────────────────────────────────────────────────────────────────────

const IconRefresh = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M13.5 8A5.5 5.5 0 1 1 10 3.07"/>
    <polyline points="10 1 10 4 13 4"/>
  </svg>
);

const IconChevronDown = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 9l6 6 6-6"/>
  </svg>
);

const IconChevronUp = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 15l-6-6-6 6"/>
  </svg>
);

const IconX = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="3" y1="3" x2="13" y2="13"/>
    <line x1="13" y1="3" x2="3" y2="13"/>
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
    className="w-[23px] h-[23px] flex items-center justify-center rounded text-[#666] hover:text-white hover:bg-white/[0.08] transition-colors disabled:opacity-40 border-none bg-transparent cursor-pointer"
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
          <div className="font-mono text-[11px] text-white leading-none">
            {Math.round(share * 100)}%
          </div>
          <div className="font-mono text-[9px] text-white mt-[3px] leading-none">
            {isOverage ? "plan maxed" : `${(planPct * 100).toFixed(1)}% of plan`}
          </div>
        </>
      ) : (
        <span className="font-mono text-[10px] text-white/30">—</span>
      )}
    </div>
  </div>
);

// ── Auth error banner ─────────────────────────────────────────────────────────

const AuthErrorBanner: React.FC<{ onRefresh: () => void; loading: boolean }> = ({ onRefresh, loading }) => (
  <div className="flex items-center gap-[7px] mx-[10px] mt-2 mb-1 px-[9px] py-[7px] rounded-[6px] bg-[rgba(255,107,107,0.08)] border border-[rgba(255,107,107,0.25)]">
    <span className="w-[6px] h-[6px] rounded-full bg-danger shrink-0" />
    <span className="font-mono text-[9px] font-semibold text-danger leading-snug flex-1">
      Session expired · run <code className="bg-white/10 px-[3px] rounded">claude</code> in a terminal, then
    </span>
    <button
      onClick={onRefresh}
      disabled={loading}
      className="font-mono text-[8px] font-bold text-danger bg-danger/10 border border-danger/25 rounded px-2 py-[3px] cursor-pointer hover:bg-danger/15 transition-colors disabled:opacity-40 shrink-0"
    >
      refresh
    </button>
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
      Make sure claude-lens<br/>is running
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
  // null = loading, true/false = resolved
  const [onboardingComplete, setOnboardingComplete] = useState<boolean | null>(null);

  useEffect(() => {
    api.getOnboardingStatus()
      .then((s) => setOnboardingComplete(s.complete))
      .catch(() => setOnboardingComplete(true)); // if invoke fails, skip onboarding
  }, []);

  // Seeds match DEFAULT_CONFIG; overwritten when config fetch resolves.
  const [warnAt, setWarnAt] = useState(0.80);
  const [critAt, setCritAt] = useState(0.90);

  useEffect(() => {
    api.getConfig()
      .then((cfg) => {
        if (cfg.warnings?.warningPercentage != null) setWarnAt(cfg.warnings.warningPercentage);
        if (cfg.warnings?.criticalPercentage != null) setCritAt(cfg.warnings.criticalPercentage);
      })
      .catch(() => { /* keep seed defaults */ });
  }, []);

  const [expanded, setExpanded] = useState(false);
  const [showTray, setShowTray] = useState(false);

  const {
    usage,
    isLoading: usageLoading,
    error: usageError,
    authError,
    isSleeping,
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

  const handleClose = useCallback(() => {
    getCurrentWindow().hide().catch((e) => console.error("[claude-lens] hide failed", e));
  }, []);

  // Reset tray when widget collapses
  useEffect(() => {
    if (!expanded) setShowTray(false);
  }, [expanded]);

  // Keep in sync with AuthErrorBanner padding (mt-2 mb-1 py-[7px] + content line-height).
  const AUTH_BANNER_HEIGHT_PX = 40;

  // Resize window for onboarding view
  useEffect(() => {
    if (onboardingComplete === false) {
      getCurrentWindow().setSize(new LogicalSize(340, 420)).catch(() => {});
    }
  }, [onboardingComplete]);

  // Resize window to fit content (main widget only)
  useEffect(() => {
    if (onboardingComplete !== true) return;
    const win = getCurrentWindow();
    const authBannerHeight = authError ? AUTH_BANNER_HEIGHT_PX : 0;
    let height: number;
    if (usageError) {
      height = 229; // header (~56) + ErrorPanel (~173)
    } else if (expanded && showTray) {
      height = 660 + authBannerHeight; // tray view: no sleep indicator
    } else if (expanded) {
      height = 679 + authBannerHeight;
    } else if (isSleeping || usage?.isStale) {
      height = 315 + authBannerHeight;
    } else {
      height = 283 + authBannerHeight;
    }
    win.setSize(new LogicalSize(340, height)).catch(() => {});
  }, [expanded, showTray, isSleeping, usage?.isStale, usageError, authError, onboardingComplete]);

  // Drag from header
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest("button")) return;
    getCurrentWindow().startDragging().catch(() => {});
  }, []);

  const { suggestions, count: suggestionCount } = useSuggestions(300_000, showTray);

  const hoursUntilWeeklyReset = usage
    ? (new Date(usage.weeklyResetsAt).getTime() - Date.now()) / (1000 * 3600)
    : Infinity;
  // "Use it or lose it" — more than half the quota left past the week's midpoint
  // TODO: 84h fires the frontend nudge slightly before the backend's first tier (72h/70%).
  // This value is intentionally different — frontend surfaces awareness earlier — but is
  // duplicated from the sidecar's trigger config. Revisit: expose a flag from GET /suggestions
  // so the threshold is defined once and both layers stay in sync.
  const isUnderutilizing = usage !== null && usage.weeklyPct < 0.50 && hoursUntilWeeklyReset <= 84;

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


  // Show nothing while we're fetching onboarding status (avoids a flash).
  if (onboardingComplete === null) return null;

  // First launch: show onboarding and return early.
  if (!onboardingComplete) {
    return <Onboarding onComplete={() => setOnboardingComplete(true)} />;
  }

  return (
    <div className="min-h-screen flex items-start justify-center p-2 bg-transparent">
      <div className="w-full rounded-[14px] bg-app-bg border border-white/[0.09] shadow-2xl shadow-black/60 overflow-hidden">

        {/* ── Header / drag region ─────────────────────────────────────────── */}
        <div
          onMouseDown={handleDragStart}
          className="flex items-center gap-[7px] px-[11px] py-[9px] border-b border-white/[0.07] cursor-grab active:cursor-grabbing select-none"
        >
          <img src="/app-icon.png" width={38} height={38} className="shrink-0 rounded-[8px]" alt="" />
          <span className="text-[12px] font-semibold text-white flex-1 tracking-[-0.01em]">
            claude-lens
          </span>
          {isSleeping && (
            <div className="w-[7px] h-[7px] rounded-full bg-[#7dd3fc] animate-pulse shrink-0" title="Sleeping" />
          )}
          {!isSleeping && usage?.isStale && (
            <div className="w-[7px] h-[7px] rounded-full bg-[#ffd200] animate-pulse shrink-0" title="Data may be stale" />
          )}
          <HeaderButton onClick={handleRefresh} disabled={usageLoading} title="Force refresh">
            <span className={usageLoading ? "animate-spin inline-block" : ""}><IconRefresh /></span>
          </HeaderButton>
          <HeaderButton onClick={() => setExpanded(v => !v)} title={expanded ? "Collapse" : "Expand"}>
            {expanded ? <IconChevronUp /> : <IconChevronDown />}
          </HeaderButton>
          <HeaderButton onClick={handleClose} title="Hide">
            <IconX />
          </HeaderButton>
        </div>

        {/* ── Auth error banner ─────────────────────────────────────────────── */}
        {!usageError && authError && (
          <AuthErrorBanner onRefresh={handleRefresh} loading={usageLoading} />
        )}

        {/* ── Error state (replaces all content) ───────────────────────────── */}
        {usageError && (
          <ErrorPanel onRetry={handleRefresh} loading={usageLoading} />
        )}

        {/* ── Collapsed view ───────────────────────────────────────────────── */}
        {!usageError && !expanded && (
          <>
            {/* Stat tiles — top row. Sleep filter intentionally excludes the
                suggestion button below: suggestions stay vivid as active CTAs. */}
            <div
              className="grid grid-cols-2 gap-[3px] p-[5px] pb-[3px]"
              style={isSleeping ? { filter: "saturate(0.2) brightness(0.75)" } : undefined}
            >
              {usageLoading && !usage ? (
                <>
                  {[0, 1].map((i) => (
                    <div
                      key={i}
                      className="rounded-[9px] min-h-[78px] bg-white/[0.07] animate-pulse"
                      style={{ animationDelay: `${i * 0.1}s` }}
                    />
                  ))}
                </>
              ) : usage ? (
                <>
                  <UsageTile type="session" pct={usage.sessionPct} resetsAt={usage.sessionResetsAt} warnAt={warnAt} critAt={critAt} />
                  <UsageTile type="weekly"  pct={usage.weeklyPct}  resetsAt={usage.weeklyResetsAt}  warnAt={warnAt} critAt={critAt} style={{ animationDelay: "0.3s" }} />
                </>
              ) : null}
            </div>

            {/* Bottom tile — full-width suggestion entry point */}
            {usageLoading && !usage ? (
              <div className="mx-[5px] mb-[3px] rounded-[9px] h-[54px] bg-white/[0.07] animate-pulse" style={{ animationDelay: "0.2s" }} />
            ) : usage ? (
              <button
                onClick={() => setExpanded(true)}
                className="w-full flex flex-row items-center justify-between px-[14px] py-[12px] cursor-pointer transition-colors"
                style={{
                  borderTop: "1px solid #1e1e1e",
                  background: isUnderutilizing ? "#0e0b00" : "#161616",
                }}
              >
                {/* Left: count + label stack */}
                <div className="flex flex-row items-center gap-[8px]">
                  <span
                    className="font-sans font-black leading-none"
                    style={{
                      fontSize: isUnderutilizing ? "3.4rem" : "2.6rem",
                      color: isUnderutilizing ? "#f5c200" : "#ffffff",
                      animation: isUnderutilizing ? "num-pulse 3.5s ease-in-out infinite" : undefined,
                    }}
                  >
                    {suggestionCount}
                  </span>
                  <div className="flex flex-col" style={{ gap: "1px" }}>
                    <span
                      className="font-mono font-bold uppercase tracking-[0.1em]"
                      style={{ fontSize: "9.5px", color: isUnderutilizing ? "#aaa" : "#ffffff" }}
                    >
                      ideas
                    </span>
                    <span
                      className="font-mono font-bold uppercase tracking-[0.1em]"
                      style={{ fontSize: "9.5px", color: isUnderutilizing ? "#888" : "#ffffff" }}
                    >
                      waiting
                    </span>
                    {isUnderutilizing && (
                      <span
                        className="font-mono font-bold uppercase tracking-[0.1em]"
                        style={{
                          fontSize: "7.5px",
                          color: "#b89000",
                          animation: "text-glow 2.8s ease-in-out infinite",
                        }}
                      >
                        use your quota
                      </span>
                    )}
                  </div>
                </div>

                {/* Right: expand cue */}
                <span
                  className="font-mono tracking-[0.08em] text-white"
                  style={{ fontSize: "8px" }}
                >
                  expand →
                </span>
              </button>
            ) : null}

            {/* Sleep / stale banner — collapsed */}
            {isSleeping
              ? <SleepIndicator />
              : usage?.isStale && <StaleIndicator isStale recordedAt={usage.recordedAt} />
            }

            <div className="pb-[9px]" />
          </>
        )}

        {/* ── Suggestion tray ──────────────────────────────────────────────── */}
        {!usageError && expanded && showTray && usage && (
          <SuggestionTray suggestions={suggestions} usage={usage} onBack={() => setShowTray(false)} />
        )}

        {/* ── Expanded view ────────────────────────────────────────────────── */}
        {!usageError && expanded && !showTray && (
          <>
            {/* 1 — Full-size usage tiles */}
            <div
              className="grid grid-cols-2 gap-[3px] p-[5px] pb-[3px]"
              style={isSleeping ? { filter: "saturate(0.2) brightness(0.75)" } : undefined}
            >
              {usageLoading && !usage ? (
                <>
                  <div className="rounded-[9px] min-h-[78px] bg-white/[0.07] animate-pulse" />
                  <div className="rounded-[9px] min-h-[78px] bg-white/[0.07] animate-pulse" style={{ animationDelay: "0.2s" }} />
                </>
              ) : usage ? (
                <>
                  <UsageTile type="session" pct={usage.sessionPct} resetsAt={usage.sessionResetsAt} warnAt={warnAt} critAt={critAt} />
                  <UsageTile type="weekly"  pct={usage.weeklyPct}  resetsAt={usage.weeklyResetsAt}  warnAt={warnAt} critAt={critAt} style={{ animationDelay: "0.3s" }} />
                </>
              ) : null}
            </div>

            {/* Sleep / stale banner — expanded */}
            {isSleeping
              ? <SleepIndicator />
              : usage?.isStale && <StaleIndicator isStale recordedAt={usage.recordedAt} />
            }

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
            <SuggestionBadge count={suggestionCount} onView={() => setShowTray(true)} />
            {suggestionCount === 0 && <div className="pb-1" />}
          </>
        )}

      </div>
    </div>
  );
}
