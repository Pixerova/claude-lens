/**
 * useSessions.ts — React hook for session data.
 *
 * Fetches recent sessions, by-source aggregates, chart data, and stats cards.
 * Refreshes on a slow 5-minute timer (session data changes infrequently).
 */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import {
  api,
  type Session,
  type SessionStats,
  type SessionsBySource,
  type ChartPoint,
} from "../lib/api";
import { type ChartDataPoint } from "../components/UsageChart";

const POLL_INTERVAL_MS  = 5 * 60 * 1000; // 5 minutes
// Enough to cover 7 days of active use (3–6 sessions/day × 7 days)
const SESSION_FETCH_LIMIT = 60;

export interface UseSessionsResult {
  sessions: Session[];
  stats: SessionStats | null;
  bySource: SessionsBySource[];
  chartData: ChartDataPoint[];   // daily cost per source
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}


export function useSessions(days = 7): UseSessionsResult {
  const [sessions, setSessions]   = useState<Session[]>([]);
  const [stats, setStats]         = useState<SessionStats | null>(null);
  const [bySource, setBySource]   = useState<SessionsBySource[]>([]);
  const [rawChart, setRawChart]   = useState<ChartPoint[]>([]);
  const [isLoading, setLoading]   = useState(true);
  const [error, setError]         = useState<string | null>(null);
  const timerRef                  = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      const [s, st, bs, cd] = await Promise.all([
        api.getSessions(SESSION_FETCH_LIMIT),
        api.getSessionStats(days),
        api.getSessionsBySource(days),
        api.getSessionsChart(days),
      ]);
      setSessions(s);
      setStats(st);
      setBySource(bs);
      setRawChart(cd);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch sessions");
    } finally {
      setLoading(false);
    }
  }, [days]);

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

  // Map API ChartPoint → ChartDataPoint (rename costUsd → value)
  const chartData = useMemo<ChartDataPoint[]>(
    () => rawChart.map((pt) => ({ day: pt.day, source: pt.source, value: pt.costUsd })),
    [rawChart],
  );

  return { sessions, stats, bySource, chartData, isLoading, error, refresh };
}

// ── Formatting helpers ────────────────────────────────────────────────────────

/** "$0.03" or "$1.20" */
export function formatCost(usd: number): string {
  if (usd < 0.01) return "< $0.01";
  return `$${usd.toFixed(2)}`;
}

/** Aggregate total cost from bySource array */
export function totalCostUsd(bySource: SessionsBySource[]): number {
  return bySource.reduce((acc, s) => acc + s.totalCostUsd, 0);
}
