/**
 * SuggestionCard.test.tsx
 *
 * Tests for SuggestionCard interactions:
 *   - Primary action button (Copy Prompt / Open Cowork) is present
 *   - "Copy prompt" → confirmation state (button text changes to "✓ Copied")
 *   - Dismiss flow → POST /suggestions/{id}/dismissed called
 *   - Snooze flow  → POST /suggestions/{id}/snoozed called with `until` body
 *
 * API calls are intercepted with vi.spyOn on the api module (no subprocess,
 * no MSW needed). Tauri's `invoke` is mocked at the module level because
 * jsdom has no window.__TAURI_INTERNALS__.
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeAll, beforeEach, afterEach } from "vitest";

// ── Mock @tauri-apps/api/core before any imports that transitively use it ──────
vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn().mockResolvedValue(undefined),
}));

// jsdom does not implement scrollIntoView; stub it so SuggestionCard's
// scroll-on-expand effect doesn't throw.
beforeAll(() => {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

import { SuggestionCard } from "./SuggestionCard";
import * as apiModule from "../lib/api";
import { Suggestion } from "../lib/api";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const MOCK_SUGGESTION: Suggestion = {
  id: "testing001",
  category: "testing",
  title: "Write missing tests",
  description: "Claude will audit your project's test coverage and write the missing tests.",
  prompt: "Audit the test coverage for my project and write the missing tests.",
  trigger: "always",
  actions: ["copy_prompt", "open_cowork"],
};

// A suggestion with only copy_prompt action (no open_cowork button)
const COPY_ONLY_SUGGESTION: Suggestion = {
  ...MOCK_SUGGESTION,
  id: "copy001",
  actions: ["copy_prompt"],
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderCard(
  suggestion: Suggestion = MOCK_SUGGESTION,
  isExpanded = true,
): {
  onToggle: ReturnType<typeof vi.fn>;
  onDismissed: ReturnType<typeof vi.fn>;
} {
  const onToggle   = vi.fn();
  const onDismissed = vi.fn();
  render(
    <SuggestionCard
      suggestion={suggestion}
      isExpanded={isExpanded}
      onToggle={onToggle}
      onDismissed={onDismissed}
    />
  );
  return { onToggle, onDismissed };
}

// ── Setup / teardown ──────────────────────────────────────────────────────────

beforeEach(() => {
  // Silence the 2-second shown timer — we don't want background API calls
  // interfering with the assertions.
  vi.spyOn(apiModule.api, "markSuggestionShown").mockResolvedValue(undefined);
  vi.spyOn(apiModule.api, "markSuggestionActedOn").mockResolvedValue(undefined);
  vi.spyOn(apiModule.api, "dismissSuggestion").mockResolvedValue(undefined);
  vi.spyOn(apiModule.api, "snoozeSuggestion").mockResolvedValue(undefined);

  // Mock clipboard
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("SuggestionCard", () => {
  // ── Primary action buttons ─────────────────────────────────────────────────

  it("renders the Copy Prompt button when copy_prompt is in actions", () => {
    renderCard(COPY_ONLY_SUGGESTION);
    expect(screen.getByRole("button", { name: /copy prompt/i })).toBeTruthy();
  });

  it("renders the Open Cowork button when open_cowork is in actions", () => {
    renderCard(MOCK_SUGGESTION);
    expect(screen.getByRole("button", { name: /open cowork/i })).toBeTruthy();
  });

  it("does not render Open Cowork button when only copy_prompt is in actions", () => {
    renderCard(COPY_ONLY_SUGGESTION);
    expect(screen.queryByRole("button", { name: /open cowork/i })).toBeNull();
  });

  // ── Copy prompt confirmation state ─────────────────────────────────────────

  it("changes Copy Prompt button text to '✓ Copied' after click", async () => {
    renderCard(COPY_ONLY_SUGGESTION);
    const btn = screen.getByRole("button", { name: /copy prompt/i });
    fireEvent.click(btn);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /copied/i })).toBeTruthy();
    });
  });

  it("calls markSuggestionActedOn when Copy Prompt is clicked", async () => {
    renderCard(COPY_ONLY_SUGGESTION);
    fireEvent.click(screen.getByRole("button", { name: /copy prompt/i }));
    await waitFor(() => {
      expect(apiModule.api.markSuggestionActedOn).toHaveBeenCalledWith("copy001");
    });
  });

  it("copies the suggestion prompt to the clipboard", async () => {
    renderCard(COPY_ONLY_SUGGESTION);
    fireEvent.click(screen.getByRole("button", { name: /copy prompt/i }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        COPY_ONLY_SUGGESTION.prompt
      );
    });
  });

  // ── Dismiss flow ───────────────────────────────────────────────────────────

  it("clicking × reveals the dismiss/snooze sheet", () => {
    renderCard();
    const xBtn = screen.getByRole("button", { name: /×/ });
    fireEvent.click(xBtn);
    expect(screen.getByText(/dismiss or snooze/i)).toBeTruthy();
  });

  it("clicking 'Dismiss permanently' calls POST /suggestions/{id}/dismissed", async () => {
    const { onDismissed } = renderCard();
    fireEvent.click(screen.getByRole("button", { name: /×/ }));
    fireEvent.click(screen.getByRole("button", { name: /dismiss permanently/i }));

    await waitFor(() => {
      expect(apiModule.api.dismissSuggestion).toHaveBeenCalledWith("testing001");
    });
    expect(onDismissed).toHaveBeenCalledWith("testing001");
  });

  // ── Snooze flow ────────────────────────────────────────────────────────────

  it("clicking 'Snooze 1 hour' calls snoozeSuggestion with an `until` timestamp", async () => {
    const before = Date.now();
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /×/ }));
    fireEvent.click(screen.getByRole("button", { name: /snooze 1 hour/i }));

    await waitFor(() => {
      expect(apiModule.api.snoozeSuggestion).toHaveBeenCalled();
    });

    const [id, until] = (apiModule.api.snoozeSuggestion as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(id).toBe("testing001");
    // `until` must be a valid ISO string and at least 1 hour from now
    const untilMs = new Date(until as string).getTime();
    expect(untilMs).toBeGreaterThan(before + 59 * 60 * 1000);
  });

  it("clicking 'Snooze until tomorrow' calls snoozeSuggestion with a tomorrow `until`", async () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /×/ }));
    fireEvent.click(screen.getByRole("button", { name: /snooze until tomorrow/i }));

    await waitFor(() => {
      expect(apiModule.api.snoozeSuggestion).toHaveBeenCalled();
    });

    const [id, until] = (apiModule.api.snoozeSuggestion as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(id).toBe("testing001");

    // `until` must be a valid ISO string in the future and must be tomorrow's date.
    const untilDate = new Date(until as string);
    expect(untilDate.getTime()).toBeGreaterThan(Date.now());

    // The component sets tomorrow at 9 AM local time, so the local date of
    // `until` must equal today's date + 1.
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    expect(untilDate.toLocaleDateString()).toBe(tomorrow.toLocaleDateString());
  });

  // ── Collapsed card ─────────────────────────────────────────────────────────

  it("does not render action buttons when the card is collapsed", () => {
    renderCard(MOCK_SUGGESTION, false /* isExpanded */);
    expect(screen.queryByRole("button", { name: /copy prompt/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /open cowork/i })).toBeNull();
  });

  it("renders the suggestion title regardless of expanded state", () => {
    renderCard(MOCK_SUGGESTION, false);
    expect(screen.getByText(MOCK_SUGGESTION.title)).toBeTruthy();
  });
});
