/**
 * useUsage.ts — React hook for live plan usage data.
 *
 * Polls the sidecar on a dynamic interval driven by the current utilisation
 * (mirroring the server-side logic so the UI stays in sync with the poller).
 * Also provides a manual refresh trigger.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { api, type UsageCurrent } from "../lib/api";

export interface UseUsageResult {
  usage: UsageCurrent | null;
  isLoading: boolean;
  error: string | null;
  authError: boolean;
  isSleeping: boolean;
  refresh: () => Promise<void>;
}

/**
 * Map utilisation → client-side poll interval (ms).
 * Kept in sync with poller.py thresholds.
 */
function getPollIntervalMs(usage: UsageCurrent | null): number {
  if (!usage) return 5 * 60 * 1000; // 5 min default while loading
  const util = Math.max(usage.sessionPct, usage.weeklyPct);
  if (util >= 0.90) return 30_000;
  if (util >= 0.80) return 60_000;
  if (util >= 0.60) return 2 * 60_000;
  if (util >= 0.20) return 5 * 60_000;
  if (util >= 0.05) return 30 * 60_000;
  return 60 * 60_000;
}

export function useUsage(): UseUsageResult {
  const [usage, setUsage]         = useState<UsageCurrent | null>(null);
  const [isLoading, setLoading]   = useState(true);
  const [error, setError]         = useState<string | null>(null);
  const [authError, setAuthError] = useState(false);
  const [isSleeping, setIsSleeping] = useState(false);
  // Incremented after every fetch attempt (success or failure) to ensure the
  // timer effect always reschedules — without this, a failed fetch leaves usage
  // unchanged and the effect never re-runs, permanently breaking the poll chain.
  const [pollSchedule, setPollSchedule] = useState(0);
  const timerRef                = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Server-reported poll interval (ms); null until first successful fetch.
  const serverIntervalMsRef     = useRef<number | null>(null);

  const fetchUsage = useCallback(async (force = false) => {
    try {
      const data = force
        ? await api.refreshUsage()
        : await api.getUsageCurrent();
      setUsage(data);
      setError(null);
      // Sync client poll cadence with the server's current interval so
      // custom thresholds in config.json are automatically respected.
      try {
        const health = await api.getHealth();
        if (health.pollIntervalSec != null) {
          serverIntervalMsRef.current = health.pollIntervalSec * 1000;
        }
        setAuthError(health.authError ?? false);
        setIsSleeping(health.isSleeping ?? false);
      } catch {
        // Health check failure is non-fatal; keep the current authError value
        // rather than clearing it, to avoid hiding a real auth problem.
        // Reset isSleeping — we can't confirm sleep state when health is
        // unreachable, so default to awake to avoid incorrectly dimming tiles.
        setIsSleeping(false);
      }
    } catch (err) {
      // A 401 from /usage/refresh means auth failure, not a sidecar outage.
      // Show the auth banner rather than the generic error panel.
      if (err instanceof Error && err.message.includes("Sidecar 401")) {
        setAuthError(true);
      } else {
        setError(err instanceof Error ? err.message : "Failed to fetch usage");
      }
    } finally {
      setLoading(false);
      setPollSchedule(n => n + 1);
    }
  }, []);

  // Schedule next poll. Uses server interval once available, otherwise
  // falls back to the local threshold table as a pre-fetch default.
  // React 18 auto-batching coalesces concurrent state updates (e.g. setUsage +
  // setPollSchedule on a successful fetch) into a single re-render, so this
  // effect fires exactly once per fetch attempt. Under React 17 or in unbatched
  // contexts, a successful fetch would trigger two effect runs and create a
  // double-timer bug — consolidate via useReducer before any backport.
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    const interval = serverIntervalMsRef.current ?? getPollIntervalMs(usage);
    timerRef.current = setTimeout(() => fetchUsage(false), interval);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [usage, fetchUsage, pollSchedule]);

  // Initial fetch
  useEffect(() => {
    fetchUsage(false);
  }, [fetchUsage]);

  const refresh = useCallback(async () => {
    setLoading(true);
    await fetchUsage(true);
  }, [fetchUsage]);

  return { usage, isLoading, error, authError, isSleeping, refresh };
}

// ── Formatting helpers (exported for use in components) ───────────────────────

/** "Resets in 4 hr 31 min" or "Resets Wed 11:00 AM" */
export function formatResetTime(isoString: string, short = false): string {
  if (!isoString) return "";
  const target = new Date(isoString);
  const now    = new Date();
  const diffMs = target.getTime() - now.getTime();

  if (diffMs <= 0) return "Resetting soon";

  const diffSec = Math.floor(diffMs / 1000);
  const hours   = Math.floor(diffSec / 3600);
  const mins    = Math.floor((diffSec % 3600) / 60);

  if (hours < 24) {
    return short
      ? `${hours}h ${mins}m`
      : `Resets in ${hours} hr ${mins} min`;
  }

  // More than 24h away — show day + time
  const dayName = target.toLocaleDateString("en-US", { weekday: "short" });
  const time    = target.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
  return short ? `${dayName} ${time}` : `Resets ${dayName} ${time}`;
}

/** "21%" */
export function formatPct(value: number): string {
  return `${Math.round(value * 100)}%`;
}
