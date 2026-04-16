/**
 * useSessions.ts — React hook for session data.
 *
 * Fetches recent sessions, by-source aggregates, chart data, and stats cards.
 * Refreshes on a slow 5-minute timer (session data changes infrequently).
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  api,
  type Session,
  type SessionStats,
  type SessionsBySource,
  type ChartPoint,
} from "../lib/api";

const POLL_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

export interface UseSessionsResult {
  sessions: Session[];
  stats: SessionStats | null;
  bySource: SessionsBySource[];
  chartData: ChartPoint[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useSessions(days = 7, limit = 20): UseSessionsResult {
  const [sessions, setSessions]   = useState<Session[]>([]);
  const [stats, setStats]         = useState<SessionStats | null>(null);
  const [bySource, setBySource]   = useState<SessionsBySource[]>([]);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [isLoading, setLoading]   = useState(true);
  const [error, setError]         = useState<string | null>(null);
  const timerRef                  = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      const [s, st, bs, cd] = await Promise.all([
        api.getSessions(limit),
        api.getSessionStats(days),
        api.getSessionsBySource(days),
        api.getSessionsChart(days),
      ]);
      setSessions(s);
      setStats(st);
      setBySource(bs);
      setChartData(cd);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch sessions");
    } finally {
      setLoading(false);
    }
  }, [days, limit]);

  // Repeat poll
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => fetchAll(), POLL_INTERVAL_MS);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [fetchAll]);

  // Initial fetch
  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const refresh = useCallback(async () => {
    setLoading(true);
    await fetchAll();
  }, [fetchAll]);

  return { sessions, stats, bySource, chartData, isLoading, error, refresh };
}

// ── Formatting helpers ────────────────────────────────────────────────────────

/** "2h 14m" or "45m" or "< 1m" */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return "< 1m";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h === 0) return `${m}m`;
  return `${h}h ${m}m`;
}

/** "$0.03" or "$1.20" */
export function formatCost(usd: number): string {
  if (usd < 0.01) return "< $0.01";
  return `$${usd.toFixed(2)}`;
}

/** Aggregate total cost from bySource array */
export function totalCostUsd(bySource: SessionsBySource[]): number {
  return bySource.reduce((acc, s) => acc + s.totalCostUsd, 0);
}
