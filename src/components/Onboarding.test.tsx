/**
 * Onboarding.test.tsx
 *
 * Tests for the two-step first-launch onboarding flow:
 *
 *   Step 1 (Keychain) — renders "Grant Access" button; on success transitions
 *     to Step 2; on failure shows the Retry button and an error note.
 *
 *   Step 2 (Ready) — fetches live plan data on mount; "Open Claude Lens" button
 *     calls completeOnboarding() and then the onComplete prop.
 *
 * Tauri window APIs are mocked at module level (jsdom has no __TAURI_INTERNALS__).
 * All sidecar API calls are intercepted with vi.spyOn on the api module.
 */

import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";

// ── Mock Tauri internals before any component import ──────────────────────────

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({
    hide: vi.fn().mockResolvedValue(undefined),
    setSize: vi.fn().mockResolvedValue(undefined),
    startDragging: vi.fn().mockResolvedValue(undefined),
  }),
}));

vi.mock("@tauri-apps/api/dpi", () => ({
  LogicalSize: class {
    constructor(public w: number, public h: number) {}
  },
}));

import Onboarding from "./Onboarding";
import * as apiModule from "../lib/api";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const AUTH_OK    = { authenticated: true,  message: "Token found." };
const AUTH_FAIL  = { authenticated: false, message: "No token found." };

const USAGE_SNAP = {
  sessionPct:      0.42,
  weeklyPct:       0.61,
  sessionResetsAt: "2099-01-01T00:00:00Z",
  weeklyResetsAt:  "2099-01-01T00:00:00Z",
  recordedAt:      new Date().toISOString(),
  isStale:         false,
};

const SESSION_STATS = {
  costToday:        0,
  costThisWeek:     0,
  totalDurationSec: 0,
  sessionCount:     7,
  mostActiveProject: "my-app",
};

// ── Setup / teardown ──────────────────────────────────────────────────────────

beforeEach(() => {
  vi.spyOn(apiModule.api, "getAuthStatus").mockResolvedValue(AUTH_OK);
  vi.spyOn(apiModule.api, "getUsageCurrent").mockResolvedValue(USAGE_SNAP);
  vi.spyOn(apiModule.api, "getSessionStats").mockResolvedValue(SESSION_STATS);
  vi.spyOn(apiModule.api, "completeOnboarding").mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Step 1: Keychain access ───────────────────────────────────────────────────

describe("Onboarding — Step 1 (Keychain)", () => {
  it("renders the Grant Access button on first render", () => {
    render(<Onboarding onComplete={vi.fn()} />);
    expect(screen.getByRole("button", { name: /grant access/i })).toBeTruthy();
  });

  it("shows 'Keychain Access' heading", () => {
    render(<Onboarding onComplete={vi.fn()} />);
    expect(screen.getByText(/keychain access/i)).toBeTruthy();
  });

  it("calls getAuthStatus when Grant Access is clicked", async () => {
    render(<Onboarding onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /grant access/i }));
    await waitFor(() => {
      expect(apiModule.api.getAuthStatus).toHaveBeenCalledTimes(1);
    });
  });

  it("shows 'Checking…' while getAuthStatus is in-flight", async () => {
    // Never resolves — keeps the button in loading state
    vi.spyOn(apiModule.api, "getAuthStatus").mockReturnValue(new Promise(() => {}));
    render(<Onboarding onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /grant access/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /checking/i })).toBeTruthy();
    });
  });

  it("transitions to Step 2 when getAuthStatus returns authenticated: true", async () => {
    vi.spyOn(apiModule.api, "getAuthStatus").mockResolvedValue(AUTH_OK);
    render(<Onboarding onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /grant access/i }));
    // Step 2 heading should appear (the success delay is 600ms — we wait it out)
    await waitFor(() => {
      expect(screen.getByText(/all set/i)).toBeTruthy();
    }, { timeout: 2000 });
  });

  it("shows Retry button when getAuthStatus returns authenticated: false", async () => {
    vi.spyOn(apiModule.api, "getAuthStatus").mockResolvedValue(AUTH_FAIL);
    render(<Onboarding onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /grant access/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /retry/i })).toBeTruthy();
    });
  });

  it("shows error note about cached data when keychain read fails", async () => {
    vi.spyOn(apiModule.api, "getAuthStatus").mockResolvedValue(AUTH_FAIL);
    render(<Onboarding onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /grant access/i }));
    await waitFor(() => {
      // This exact phrase only appears in the error banner, not the idle skip-note
      expect(screen.getByText(/cached data until access is granted/i)).toBeTruthy();
    });
  });

  it("shows Retry button when getAuthStatus rejects (network error)", async () => {
    vi.spyOn(apiModule.api, "getAuthStatus").mockRejectedValue(new Error("Network error"));
    render(<Onboarding onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /grant access/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /retry/i })).toBeTruthy();
    });
  });

  it("Retry button re-invokes getAuthStatus", async () => {
    vi.spyOn(apiModule.api, "getAuthStatus")
      .mockResolvedValueOnce(AUTH_FAIL)
      .mockResolvedValue(AUTH_OK);

    render(<Onboarding onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /grant access/i }));

    await waitFor(() => screen.getByRole("button", { name: /retry/i }));
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      expect(apiModule.api.getAuthStatus).toHaveBeenCalledTimes(2);
    });
  });
});

// ── Step 2: Ready ─────────────────────────────────────────────────────────────

describe("Onboarding — Step 2 (Ready)", () => {
  /**
   * Helper: render Onboarding and fast-forward through Step 1 success
   * so the component lands on Step 2 before we start asserting.
   */
  async function renderOnStep2(onComplete = vi.fn()) {
    vi.spyOn(apiModule.api, "getAuthStatus").mockResolvedValue(AUTH_OK);
    render(<Onboarding onComplete={onComplete} />);
    fireEvent.click(screen.getByRole("button", { name: /grant access/i }));
    await waitFor(() => screen.getByText(/all set/i), { timeout: 2000 });
    return { onComplete };
  }

  it("renders the 'All set' heading on Step 2", async () => {
    await renderOnStep2();
    expect(screen.getByText(/all set/i)).toBeTruthy();
  });

  it("calls getUsageCurrent on mount of Step 2", async () => {
    await renderOnStep2();
    await waitFor(() => {
      expect(apiModule.api.getUsageCurrent).toHaveBeenCalledTimes(1);
    });
  });

  it("calls getSessionStats on mount of Step 2", async () => {
    await renderOnStep2();
    await waitFor(() => {
      expect(apiModule.api.getSessionStats).toHaveBeenCalledTimes(1);
    });
  });

  it("shows the session % from the live reading", async () => {
    await renderOnStep2();
    // USAGE_SNAP.sessionPct = 0.42 → renders as "42%"
    await waitFor(() => {
      expect(screen.getByText("42%")).toBeTruthy();
    });
  });

  it("shows the weekly % from the live reading", async () => {
    await renderOnStep2();
    await waitFor(() => {
      expect(screen.getByText("61%")).toBeTruthy();
    });
  });

  it("shows session count when sessions exist", async () => {
    await renderOnStep2();
    // SESSION_STATS.sessionCount = 7
    await waitFor(() => {
      expect(screen.getByText(/7 local session/i)).toBeTruthy();
    });
  });

  it("renders the Open Claude Lens button", async () => {
    await renderOnStep2();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /open claude lens/i })).toBeTruthy();
    });
  });

  it("calls completeOnboarding when Open Claude Lens is clicked", async () => {
    const { onComplete } = await renderOnStep2();
    await waitFor(() => screen.getByRole("button", { name: /open claude lens/i }));
    fireEvent.click(screen.getByRole("button", { name: /open claude lens/i }));
    await waitFor(() => {
      expect(apiModule.api.completeOnboarding).toHaveBeenCalledTimes(1);
    });
  });

  it("calls onComplete prop after completeOnboarding resolves", async () => {
    const onComplete = vi.fn();
    await renderOnStep2(onComplete);
    await waitFor(() => screen.getByRole("button", { name: /open claude lens/i }));
    fireEvent.click(screen.getByRole("button", { name: /open claude lens/i }));
    await waitFor(() => {
      expect(onComplete).toHaveBeenCalledTimes(1);
    });
  });

  it("still calls onComplete even when completeOnboarding rejects", async () => {
    vi.spyOn(apiModule.api, "completeOnboarding").mockRejectedValue(
      new Error("disk full")
    );
    const onComplete = vi.fn();
    await renderOnStep2(onComplete);
    await waitFor(() => screen.getByRole("button", { name: /open claude lens/i }));
    fireEvent.click(screen.getByRole("button", { name: /open claude lens/i }));
    // onComplete must fire even on write failure — widget opens regardless
    await waitFor(() => {
      expect(onComplete).toHaveBeenCalledTimes(1);
    });
  });

  it("renders gracefully when getUsageCurrent rejects", async () => {
    vi.spyOn(apiModule.api, "getUsageCurrent").mockRejectedValue(
      new Error("sidecar unreachable")
    );
    await renderOnStep2();
    // Should not throw — usage tiles absent but Open button still present
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /open claude lens/i })).toBeTruthy();
    });
  });
});
