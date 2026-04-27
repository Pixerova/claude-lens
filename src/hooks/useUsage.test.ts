/**
 * useUsage.test.ts
 *
 * Focuses on the polling-chain invariant: the auto-poll timer must always be
 * rescheduled after a fetch attempt, whether it succeeds or fails.
 *
 * Regression for the overnight-stale bug: when fetchUsage threw (network down,
 * sidecar unreachable, auth error), usage state was unchanged, the timer
 * useEffect never re-ran, and polling silently stopped forever.
 *
 * Note: all time-advancement uses act(advanceTimersByTimeAsync) rather than
 * waitFor — waitFor's internal setInterval is frozen under fake timers and
 * causes hangs.
 */

import { renderHook, act } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { useUsage } from "./useUsage";
import * as apiModule from "../lib/api";

// Drain pending promises + React state updates without advancing the clock.
const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });

// Advance the fake clock by ms, draining all timers and promises along the way.
const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

const NETWORK_ERROR = new Error("Failed to fetch");

const freshSnapshot = {
  sessionPct: 0.45,
  weeklyPct: 0.30,
  sessionResetsAt: new Date(Date.now() + 3 * 3600 * 1000).toISOString(),
  weeklyResetsAt: new Date(Date.now() + 5 * 24 * 3600 * 1000).toISOString(),
  recordedAt: new Date().toISOString(),
  isStale: false,
};

const staleSnapshot = { ...freshSnapshot, isStale: true };

const healthOk = {
  status: "ok",
  authenticated: true,
  authError: false,
  lastPollAt: new Date().toISOString(),
  pollIntervalSec: 300,
  isStale: false,
  stalenessSeconds: 0,
  isSleeping: false,
  activeUntil: null,
  db: { snapshot_count: 1, session_count: 0, suggestion_count: 0, db_size_bytes: 0 },
};

const healthAuthError = { ...healthOk, authError: true, authenticated: false };

describe("useUsage polling chain", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("keeps polling after a network failure — the poll chain must not break", async () => {
    // First call fails (sidecar unreachable overnight), second succeeds (morning recovery).
    const getUsageCurrent = vi
      .spyOn(apiModule.api, "getUsageCurrent")
      .mockRejectedValueOnce(NETWORK_ERROR)
      .mockResolvedValue(freshSnapshot);

    // getHealth is only reachable after getUsageCurrent succeeds — applies to call #2.
    vi.spyOn(apiModule.api, "getHealth").mockResolvedValue(healthOk);

    const { result } = renderHook(() => useUsage());

    // Drain the initial async fetch (rejection).
    await flush();

    // Usage is still null — the failure left it untouched.
    expect(result.current.isLoading).toBe(false);
    expect(result.current.usage).toBeNull();
    expect(result.current.error).toMatch(/Failed to fetch/);
    expect(getUsageCurrent).toHaveBeenCalledTimes(1);

    // Advance past the next scheduled poll (5-min default when usage=null).
    await tick(5 * 60 * 1000 + 100);

    // The poll chain must have survived: second call fired and succeeded.
    expect(getUsageCurrent).toHaveBeenCalledTimes(2);
    expect(result.current.usage?.isStale).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("keeps polling after consecutive failures", async () => {
    const getUsageCurrent = vi
      .spyOn(apiModule.api, "getUsageCurrent")
      .mockRejectedValueOnce(NETWORK_ERROR)
      .mockRejectedValueOnce(NETWORK_ERROR)
      .mockResolvedValue(freshSnapshot);

    vi.spyOn(apiModule.api, "getHealth").mockResolvedValue(healthOk);

    renderHook(() => useUsage());

    // First fetch (immediate on mount) — fails.
    await flush();
    expect(getUsageCurrent).toHaveBeenCalledTimes(1);

    // Second poll window — also fails, but chain must still be alive.
    await tick(5 * 60 * 1000 + 100);
    expect(getUsageCurrent).toHaveBeenCalledTimes(2);

    // Third poll window — succeeds.
    await tick(5 * 60 * 1000 + 100);
    expect(getUsageCurrent).toHaveBeenCalledTimes(3);
  });

  it("reschedules automatic polling after a manual refresh", async () => {
    const getUsageCurrent = vi
      .spyOn(apiModule.api, "getUsageCurrent")
      .mockResolvedValue(freshSnapshot);
    vi.spyOn(apiModule.api, "refreshUsage").mockResolvedValue(freshSnapshot);
    vi.spyOn(apiModule.api, "getHealth").mockResolvedValue(healthOk);

    const { result } = renderHook(() => useUsage());
    await flush(); // initial fetch

    await act(async () => { void result.current.refresh(); });
    await flush(); // refresh settles

    // Advance one full poll window — automatic polling must still fire.
    await tick(300 * 1000 + 100);
    // 1 initial + 1 auto-poll after refresh = 2 getUsageCurrent calls total.
    expect(getUsageCurrent).toHaveBeenCalledTimes(2);
  });

  it("clears authError and isStale once sidecar recovers", async () => {
    // Simulate overnight: stale data + auth error; recovery on second poll.
    vi.spyOn(apiModule.api, "getUsageCurrent")
      .mockResolvedValueOnce(staleSnapshot)
      .mockResolvedValue(freshSnapshot);

    vi.spyOn(apiModule.api, "getHealth")
      .mockResolvedValueOnce(healthAuthError)
      .mockResolvedValue(healthOk);

    const { result } = renderHook(() => useUsage());

    // First poll settles with stale snapshot and auth error.
    await flush();
    expect(result.current.usage?.isStale).toBe(true);
    expect(result.current.authError).toBe(true);

    // Advance to the next scheduled poll (server reported 300 s interval).
    await tick(300 * 1000 + 100);

    // Recovery: stale indicator and auth banner must clear.
    expect(result.current.usage?.isStale).toBe(false);
    expect(result.current.authError).toBe(false);
  });
});
