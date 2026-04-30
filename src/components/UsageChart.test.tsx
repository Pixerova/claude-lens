/**
 * UsageChart.test.tsx
 *
 * Tests for UsageChart:
 *   - Zero-cost anomaly: all values zero → fallback text rendered, no misleading bars
 *   - Non-zero data → chart container rendered (no fallback)
 *
 * Recharts' ResponsiveContainer relies on real DOM layout measurements that
 * jsdom cannot provide. We stub ResizeObserver (required by recharts internals)
 * and verify structural behaviour rather than SVG pixel output.
 */

import { render, screen } from "@testing-library/react";
import { vi, describe, it, expect, beforeAll } from "vitest";
import { UsageChart, ChartDataPoint } from "./UsageChart";

// ── ResizeObserver stub required by recharts ResponsiveContainer ──────────────
beforeAll(() => {
  class MockResizeObserver {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
    constructor(_cb: ResizeObserverCallback) {}
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).ResizeObserver = MockResizeObserver;
});

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Build today's YYYY-MM-DD string in local time (matches the chart scaffold). */
function today(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Build a 7-day dataset with non-zero costs on today for both sources. */
function buildNonZeroData(): ChartDataPoint[] {
  return [
    { day: today(), source: "code",   value: 0.10 },
    { day: today(), source: "cowork", value: 0.05 },
  ];
}

/** Build a 7-day dataset where every value is 0 (zero-cost anomaly). */
function buildAllZeroData(): ChartDataPoint[] {
  const days: ChartDataPoint[] = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const iso = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
    days.push({ day: iso, source: "code",   value: 0 });
    days.push({ day: iso, source: "cowork", value: 0 });
  }
  return days;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("UsageChart", () => {
  it("shows fallback text when data array is empty", () => {
    render(<UsageChart data={[]} unit="cost" />);
    expect(screen.getByText("No data yet.")).toBeTruthy();
  });

  it("uses a custom emptyLabel when provided", () => {
    render(<UsageChart data={[]} unit="cost" emptyLabel="Nothing to show" />);
    expect(screen.getByText("Nothing to show")).toBeTruthy();
  });

  it("shows fallback when all cost values are zero — zero-cost anomaly guard", () => {
    // All-zero data must NOT render misleading equal-height bars.
    // The component detects this and falls back to text.
    const { container } = render(
      <UsageChart data={buildAllZeroData()} unit="cost" />
    );
    // Fallback paragraph must appear
    const fallback = container.querySelector("p");
    expect(fallback).not.toBeNull();
    // No recharts SVG bars should be present
    expect(container.querySelector(".recharts-responsive-container")).toBeNull();
  });

  it("renders the recharts container (not fallback) when data has non-zero values", () => {
    const { container } = render(
      <UsageChart data={buildNonZeroData()} unit="cost" />
    );
    // Fallback text must NOT appear
    expect(container.querySelector("p")).toBeNull();
    // The recharts responsive container must be in the DOM
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
  });

});
