/**
 * api.ts — Typed client for the Claude Lens Python sidecar (localhost:8765).
 *
 * All fetch calls go through `sidecarFetch` which handles the base URL,
 * JSON parsing, and error normalisation.
 */

const BASE_URL = "http://127.0.0.1:8765";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface UsageCurrent {
  sessionPct: number;       // 0–1
  sessionResetsAt: string;  // ISO 8601 UTC
  weeklyPct: number;        // 0–1
  weeklyResetsAt: string;   // ISO 8601 UTC
  recordedAt: string;       // ISO 8601 UTC
  isStale: boolean;
}

export interface UsageHistoryPoint {
  recordedAt: string;
  sessionPct: number;
  weeklyPct: number;
}

export interface Session {
  sessionId: string;
  source: "code" | "cowork";
  startedAt: string;
  endedAt: string;
  durationSec: number;
  model: string;
  project: string | null;
  costUsd: number;
  title: string | null;       // first user message text, max 200 chars
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  pctOfWeek: number;          // 0–1, share of this week's total tracked cost
}

export interface SessionStats {
  costToday: number;
  costThisWeek: number;
  totalDurationSec: number;
  sessionCount: number;
  mostActiveProject: string | null;
}

export interface SessionsBySource {
  source: "code" | "cowork";
  sessionCount: number;
  totalDurationSec: number;
  totalCostUsd: number;
}

export interface ChartPoint {
  day: string;   // YYYY-MM-DD
  source: "code" | "cowork";
  costUsd: number;
}

export interface Health {
  status: string;
  authenticated: boolean;
  lastPollAt: string | null;
  pollIntervalSec: number | null;
  isStale: boolean;
  stalenessSeconds: number | null;
  db: {
    snapshot_count: number;
    session_count: number;
    suggestion_count: number;
    db_size_bytes: number;
  };
}

export interface AuthStatus {
  authenticated: boolean;
  message: string;
}

// ── Fetch helper ──────────────────────────────────────────────────────────────

async function sidecarFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Sidecar ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

// ── API methods ───────────────────────────────────────────────────────────────

export const api = {
  /** Latest plan usage snapshot. Always returns something; check isStale. */
  getUsageCurrent(): Promise<UsageCurrent> {
    return sidecarFetch<UsageCurrent>("/usage/current");
  },

  /** Force an immediate OAuth API poll. */
  refreshUsage(): Promise<UsageCurrent> {
    return sidecarFetch<UsageCurrent>("/usage/refresh", { method: "POST" });
  },

  /** Plan usage history for trend charts. */
  getUsageHistory(days = 7): Promise<UsageHistoryPoint[]> {
    return sidecarFetch<UsageHistoryPoint[]>(`/usage/history?days=${days}`);
  },

  /** Recent sessions, newest first. Each includes pctOfWeek. */
  getSessions(limit = 20): Promise<Session[]> {
    return sidecarFetch<Session[]>(`/sessions?limit=${limit}`);
  },

  /** Aggregate stats for the stats cards. */
  getSessionStats(days = 7): Promise<SessionStats> {
    return sidecarFetch<SessionStats>(`/sessions/stats?days=${days}`);
  },

  /** Aggregate stats grouped by source. */
  getSessionsBySource(days = 7): Promise<SessionsBySource[]> {
    return sidecarFetch<SessionsBySource[]>(`/sessions/by-source?days=${days}`);
  },

  /** Daily cost per source for the stacked bar chart. */
  getSessionsChart(days = 7): Promise<ChartPoint[]> {
    return sidecarFetch<ChartPoint[]>(`/sessions/chart?days=${days}`);
  },

  /** Sidecar health and auth status. */
  getHealth(): Promise<Health> {
    return sidecarFetch<Health>("/health");
  },

  /** Check Keychain auth status. */
  getAuthStatus(): Promise<AuthStatus> {
    return sidecarFetch<AuthStatus>("/auth/status");
  },
};
