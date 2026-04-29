/**
 * App.onboarding.test.tsx
 *
 * Targeted tests for the onboarding gate in App.tsx.
 *
 * The gate logic is:
 *   onboardingComplete === null  → render nothing (loading)
 *   onboardingComplete === false → render <Onboarding>
 *   onboardingComplete === true  → render the main widget
 *   getOnboardingStatus rejects  → fall back to true (render main widget)
 *
 * Strategy: mock every hook and API the full App depends on so tests stay
 * fast and don't require a running sidecar. Only the onboarding gate
 * behaviour is asserted.
 */

import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";

// ── Mock Tauri internals (jsdom has no __TAURI_INTERNALS__) ───────────────────

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({
    hide:         vi.fn().mockResolvedValue(undefined),
    setSize:      vi.fn().mockResolvedValue(undefined),
    startDragging: vi.fn().mockResolvedValue(undefined),
  }),
}));

vi.mock("@tauri-apps/api/dpi", () => ({
  LogicalSize: class {
    constructor(public w: number, public h: number) {}
  },
}));

// ── Mock hooks so the full widget doesn't need a live sidecar ─────────────────

vi.mock("./hooks/useUsage", () => ({
  useUsage: () => ({
    usage: null,
    isLoading: false,
    error: "sidecar not running",
    authError: false,
    isSleeping: false,
    refresh: vi.fn(),
  }),
}));

vi.mock("./hooks/useSessions", () => ({
  useSessions: () => ({
    sessions: [],
    stats: null,
    bySource: [],
    chartData: [],
    isLoading: false,
    refresh: vi.fn(),
  }),
  totalCostUsd: () => 0,
}));

vi.mock("./hooks/useSuggestions", () => ({
  useSuggestions: () => ({ suggestions: [], count: 0 }),
}));

import App from "./App";
import * as apiModule from "./lib/api";

// ── Shared stubs ──────────────────────────────────────────────────────────────

const AUTH_OK   = { authenticated: true,  message: "" };
const USAGE_SNAP = {
  sessionPct: 0.1, weeklyPct: 0.2,
  sessionResetsAt: "2099-01-01T00:00:00Z",
  weeklyResetsAt:  "2099-01-01T00:00:00Z",
  recordedAt:      new Date().toISOString(),
  isStale: false,
};
const SESSION_STATS = {
  costToday: 0, costThisWeek: 0, totalDurationSec: 0,
  sessionCount: 0, mostActiveProject: null,
};

// ── Setup / teardown ──────────────────────────────────────────────────────────

beforeEach(() => {
  // Stub every API method the onboarding component might call
  vi.spyOn(apiModule.api, "getAuthStatus").mockResolvedValue(AUTH_OK);
  vi.spyOn(apiModule.api, "getUsageCurrent").mockResolvedValue(USAGE_SNAP);
  vi.spyOn(apiModule.api, "getSessionStats").mockResolvedValue(SESSION_STATS);
  vi.spyOn(apiModule.api, "completeOnboarding").mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ══════════════════════════════════════════════════════════════════════════════
// Onboarding gate
// ══════════════════════════════════════════════════════════════════════════════

describe("App — onboarding gate", () => {
  it("renders nothing while the onboarding status fetch is in-flight", () => {
    // getOnboardingStatus never resolves → component stays in null state
    vi.spyOn(apiModule.api, "getOnboardingStatus").mockReturnValue(
      new Promise(() => {})
    );

    const { container } = render(<App />);
    // The gate returns null during loading, so the root is empty
    expect(container.firstChild).toBeNull();
  });

  it("renders <Onboarding> when onboardingComplete is false", async () => {
    vi.spyOn(apiModule.api, "getOnboardingStatus").mockResolvedValue({
      complete: false,
    });

    render(<App />);

    // Onboarding component renders "Grant Access" button (Step 1)
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /grant access/i })).toBeTruthy();
    });
  });

  it("renders the main widget when onboardingComplete is true", async () => {
    vi.spyOn(apiModule.api, "getOnboardingStatus").mockResolvedValue({
      complete: true,
    });

    render(<App />);

    // The main widget header contains 'claude-lens' text
    await waitFor(() => {
      expect(screen.getByText("claude-lens")).toBeTruthy();
    });
  });

  it("falls back to the main widget when getOnboardingStatus rejects", async () => {
    vi.spyOn(apiModule.api, "getOnboardingStatus").mockRejectedValue(
      new Error("sidecar unreachable")
    );

    render(<App />);

    // On rejection we set onboardingComplete = true → main widget
    await waitFor(() => {
      expect(screen.getByText("claude-lens")).toBeTruthy();
    });
  });

  it("switches from <Onboarding> to main widget after onComplete fires", async () => {
    vi.spyOn(apiModule.api, "getOnboardingStatus").mockResolvedValue({
      complete: false,
    });

    render(<App />);

    // Wait for Onboarding to appear
    await waitFor(() =>
      screen.getByRole("button", { name: /grant access/i })
    );

    // Simulate getAuthStatus success → step 2 → click Open
    vi.spyOn(apiModule.api, "getAuthStatus").mockResolvedValue(AUTH_OK);

    // Fast-forward through the keychain step
    const grantBtn = screen.getByRole("button", { name: /grant access/i });
    grantBtn.click();

    // Step 2 should appear (after the 600 ms success delay)
    await waitFor(() => screen.getByText(/all set/i), { timeout: 2000 });

    const openBtn = screen.getByRole("button", { name: /open claude lens/i });
    openBtn.click();

    // Main widget should replace the onboarding screen
    await waitFor(() => {
      expect(screen.getByText("claude-lens")).toBeTruthy();
      expect(screen.queryByText(/all set/i)).toBeNull();
    });
  });
});
