/**
 * UsageTile.test.tsx
 *
 * Tests for UsageTile (percentage display, alert-level CSS classes, pulse
 * animation) and its companion indicator components StaleIndicator and
 * SleepIndicator which are rendered alongside tiles in the app.
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { UsageTile } from "./UsageTile";
import { StaleIndicator } from "./StaleIndicator";
import { SleepIndicator } from "./SleepIndicator";

const FUTURE_RESET = "2099-01-01T00:00:00Z";

// ── UsageTile ─────────────────────────────────────────────────────────────────

describe("UsageTile", () => {
  it("renders session percentage text correctly", () => {
    const { container } = render(
      <UsageTile type="session" pct={0.45} resetsAt={FUTURE_RESET} />
    );
    expect(container.textContent).toContain("45%");
  });

  it("renders weekly percentage text correctly", () => {
    const { container } = render(
      <UsageTile type="weekly" pct={0.30} resetsAt={FUTURE_RESET} />
    );
    expect(container.textContent).toContain("30%");
  });

  // ── Alert level boundaries ────────────────────────────────────────────────

  it("applies normal CSS class at 79% — no warning", () => {
    const { container } = render(
      <UsageTile type="session" pct={0.79} resetsAt={FUTURE_RESET} />
    );
    const el = container.firstElementChild as HTMLElement;
    expect(el.className).toContain("bg-tile-sess-norm");
    expect(el.className).not.toContain("bg-tile-sess-warn");
    expect(el.className).not.toContain("bg-tile-sess-crit");
  });

  it("applies warning CSS class at exactly 80%", () => {
    const { container } = render(
      <UsageTile type="session" pct={0.80} resetsAt={FUTURE_RESET} />
    );
    const el = container.firstElementChild as HTMLElement;
    expect(el.className).toContain("bg-tile-sess-warn");
    expect(el.className).not.toContain("bg-tile-sess-norm");
    expect(el.className).not.toContain("bg-tile-sess-crit");
  });

  it("applies critical CSS class at exactly 90%", () => {
    const { container } = render(
      <UsageTile type="session" pct={0.90} resetsAt={FUTURE_RESET} />
    );
    const el = container.firstElementChild as HTMLElement;
    expect(el.className).toContain("bg-tile-sess-crit");
    expect(el.className).not.toContain("bg-tile-sess-norm");
    expect(el.className).not.toContain("bg-tile-sess-warn");
  });

  it("adds animate-flash class at exactly 90% (critical pulse)", () => {
    const { container } = render(
      <UsageTile type="session" pct={0.90} resetsAt={FUTURE_RESET} />
    );
    const el = container.firstElementChild as HTMLElement;
    expect(el.className).toContain("animate-flash");
  });

  it("does NOT add animate-flash below 90%", () => {
    const { container } = render(
      <UsageTile type="session" pct={0.89} resetsAt={FUTURE_RESET} />
    );
    const el = container.firstElementChild as HTMLElement;
    expect(el.className).not.toContain("animate-flash");
  });

  it("uses weekly-specific CSS classes for type=weekly", () => {
    const { container } = render(
      <UsageTile type="weekly" pct={0.80} resetsAt={FUTURE_RESET} />
    );
    const el = container.firstElementChild as HTMLElement;
    expect(el.className).toContain("bg-tile-week-warn");
    expect(el.className).not.toContain("bg-tile-sess-warn");
  });
});

// ── StaleIndicator ────────────────────────────────────────────────────────────

describe("StaleIndicator", () => {
  it("renders stale banner when isStale is true", () => {
    const { container } = render(<StaleIndicator isStale={true} />);
    expect(container.textContent?.toLowerCase()).toContain("stale");
    expect(container.innerHTML).not.toBe("");
  });

  it("renders nothing when isStale is false", () => {
    const { container } = render(<StaleIndicator isStale={false} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders error state when error prop is provided", () => {
    const { container } = render(
      <StaleIndicator isStale={false} error="Sidecar unreachable" />
    );
    expect(container.innerHTML).not.toBe("");
    expect(container.textContent?.toLowerCase()).toContain("unreachable");
  });
});

// ── SleepIndicator ────────────────────────────────────────────────────────────

describe("SleepIndicator", () => {
  it("renders the sleep banner", () => {
    const { container } = render(<SleepIndicator />);
    expect(container.innerHTML).not.toBe("");
    expect(container.textContent?.toLowerCase()).toContain("sleep");
  });
});
