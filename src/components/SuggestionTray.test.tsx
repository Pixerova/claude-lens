import { render, screen } from "@testing-library/react";
import { vi, describe, it, expect, beforeAll } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn().mockResolvedValue(undefined),
}));

beforeAll(() => {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

import { SuggestionTray } from "./SuggestionTray";
import { Suggestion, UsageCurrent } from "../lib/api";

const FUTURE_RESET = "2099-01-01T00:00:00Z";
const THRESHOLDS = { warnAt: 0.80, critAt: 0.90 };

const MOCK_USAGE: UsageCurrent = {
  sessionPct: 0.45,
  sessionResetsAt: FUTURE_RESET,
  weeklyPct: 0.30,
  weeklyResetsAt: FUTURE_RESET,
  recordedAt: FUTURE_RESET,
  isStale: false,
};

const MOCK_SUGGESTION: Suggestion = {
  id: "sug-001",
  category: "testing",
  title: "Write missing tests",
  description: "Add tests for uncovered components.",
  prompt: "Write the missing tests.",
  trigger: "low_coverage",
  actions: [],
};

describe("SuggestionTray", () => {
  it("renders without crashing and shows both stat tiles", () => {
    render(
      <SuggestionTray
        suggestions={[MOCK_SUGGESTION]}
        usage={MOCK_USAGE}
        onBack={vi.fn()}
        {...THRESHOLDS}
      />
    );
    expect(screen.getByText("45%")).toBeTruthy();
    expect(screen.getByText("30%")).toBeTruthy();
  });

  it("renders the suggestion card title", () => {
    render(
      <SuggestionTray
        suggestions={[MOCK_SUGGESTION]}
        usage={MOCK_USAGE}
        onBack={vi.fn()}
        {...THRESHOLDS}
      />
    );
    expect(screen.getByText("Write missing tests")).toBeTruthy();
  });

  it("shows empty state when all suggestions are dismissed", () => {
    render(
      <SuggestionTray
        suggestions={[]}
        usage={MOCK_USAGE}
        onBack={vi.fn()}
        {...THRESHOLDS}
      />
    );
    expect(screen.getByText(/all suggestions dismissed/i)).toBeTruthy();
  });
});
