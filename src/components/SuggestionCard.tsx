import React, { useState, useCallback, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { api, Suggestion } from "../lib/api";

const CATEGORY_COLORS: Record<string, string> = {
  testing:       "#3b82f6",
  security:      "#ef4444",
  code_health:   "#22c55e",
  documentation: "#f59e0b",
  dependencies:  "#a855f7",
  maintenance:   "#f97316",
  productivity:  "#06b6d4",
  product:       "#06b6d4",
};

const TRIGGER_LABELS: Record<string, string> = {
  low_utilization_eow: "Use your quota this week",
  post_reset:          "After quota reset",
  always:              "Anytime",
};

function tomorrowAt9am(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(9, 0, 0, 0); // 9 AM in the user's local timezone
  return d.toISOString(); // converts to UTC ISO — sidecar compares in UTC
}

interface SuggestionCardProps {
  suggestion: Suggestion;
  isExpanded: boolean;
  onToggle: () => void;
  onDismissed: (id: string) => void;
}

export const SuggestionCard: React.FC<SuggestionCardProps> = ({
  suggestion,
  isExpanded,
  onToggle,
  onDismissed,
}) => {
  const [showDismissSheet, setShowDismissSheet] = useState(false);
  const [copyConfirmed, setCopyConfirmed] = useState(false);
  const [openConfirmed, setOpenConfirmed] = useState(false);
  const [openHovered, setOpenHovered] = useState(false);
  const [copyHovered, setCopyHovered] = useState(false);
  const [snooze1hHovered, setSnooze1hHovered] = useState(false);
  const [snoozeTomorrowHovered, setSnoozeTomorrowHovered] = useState(false);
  const [dismissPermHovered, setDismissPermHovered] = useState(false);
  const [cancelHovered, setCancelHovered] = useState(false);

  const expandedBodyRef = useRef<HTMLDivElement>(null);

  // Scroll expanded content into view so the last card in the list isn't
  // clipped by the overflow-y-auto scroll container.
  useEffect(() => {
    if (isExpanded && expandedBodyRef.current) {
      expandedBodyRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [isExpanded]);

  // Persists for the lifetime of this component instance; guards against
  // recording shown_at more than once per card mount even when the card
  // collapses and re-expands or when an action fires before the timer.
  const shownRecorded = useRef(false);
  const shownTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Start a 2-second timer when expanded; cancel it if the card collapses first.
  // Records shown_at only after the user has genuinely read the card.
  useEffect(() => {
    if (isExpanded) {
      shownTimer.current = setTimeout(() => {
        if (!shownRecorded.current) {
          shownRecorded.current = true;
          api.markSuggestionShown(suggestion.id, suggestion.trigger).catch(() => {});
        }
      }, 2000);
    } else {
      if (shownTimer.current !== null) {
        clearTimeout(shownTimer.current);
        shownTimer.current = null;
      }
    }
    return () => {
      if (shownTimer.current !== null) {
        clearTimeout(shownTimer.current);
        shownTimer.current = null;
      }
    };
  }, [isExpanded, suggestion.id]);

  const color = CATEGORY_COLORS[suggestion.category] ?? "#888";
  const truncatedPrompt =
    suggestion.prompt.length > 110
      ? suggestion.prompt.slice(0, 110) + "…"
      : suggestion.prompt;
  const triggerLabel = TRIGGER_LABELS[suggestion.trigger] ?? suggestion.trigger;

  const recordShownIfNeeded = useCallback(() => {
    if (!shownRecorded.current) {
      shownRecorded.current = true;
      if (shownTimer.current !== null) {
        clearTimeout(shownTimer.current);
        shownTimer.current = null;
      }
      api.markSuggestionShown(suggestion.id, suggestion.trigger).catch(() => {});
    }
  }, [suggestion.id, suggestion.trigger]);

  const handleCopy = useCallback(async () => {
    recordShownIfNeeded();
    await navigator.clipboard.writeText(suggestion.prompt);
    api.markSuggestionActedOn(suggestion.id).catch(() => {});
    setCopyConfirmed(true);
    setTimeout(() => setCopyConfirmed(false), 2000);
  }, [suggestion, recordShownIfNeeded]);

  const handleOpen = useCallback(async () => {
    recordShownIfNeeded();
    await navigator.clipboard.writeText(suggestion.prompt);
    api.markSuggestionActedOn(suggestion.id).catch(() => {});
    try {
      await invoke("open_claude_app");
    } catch {
      // Prompt is on clipboard; user can paste manually if app launch fails
    }
    setOpenConfirmed(true);
    setTimeout(() => setOpenConfirmed(false), 2000);
  }, [suggestion, recordShownIfNeeded]);

  const handleSnooze = useCallback(async (until: string) => {
    await api.snoozeSuggestion(suggestion.id, until);
    setShowDismissSheet(false);
    onDismissed(suggestion.id);
  }, [suggestion.id, onDismissed]);

  const handleDismiss = useCallback(async () => {
    await api.dismissSuggestion(suggestion.id);
    setShowDismissSheet(false);
    onDismissed(suggestion.id);
  }, [suggestion.id, onDismissed]);

  return (
    <div className="relative" style={{ borderTop: "1px solid #222", background: "#1a1a1a" }}>
      {/* Card header — always visible, tap to expand */}
      <div
        className="flex flex-col cursor-pointer px-[14px] pt-[11px] pb-[11px]"
        style={{ gap: "6px" }}
        onClick={onToggle}
      >
        {/* Category badge + chevron */}
        <div className="flex items-center justify-between">
          <span
            className="font-mono font-bold uppercase tracking-[0.1em]"
            style={{
              fontSize: "11px",
              padding: "2px 6px",
              borderRadius: "2px",
              background: `${color}22`,
              color,
            }}
          >
            {suggestion.category.replace(/_/g, " ")}
          </span>
          <span
            className="transition-transform duration-200 flex items-center justify-center w-[23px] h-[23px]"
            style={{
              display: "inline-flex",
              color: "#666",
              transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 9l6 6 6-6"/>
            </svg>
          </span>
        </div>

        {/* Title */}
        <p
          className="font-mono font-bold tracking-[0.02em]"
          style={{ fontSize: "13px", color: "#e0e0e0", lineHeight: 1.35, margin: 0 }}
        >
          {suggestion.title}
        </p>

        {/* Trigger line */}
        <div className="flex items-center gap-[5px]">
          <div
            className="rounded-full shrink-0"
            style={{ width: "5px", height: "5px", background: "#f5c200" }}
          />
          <span
            className="font-mono tracking-[0.03em]"
            style={{ fontSize: "11px", color: "#888" }}
          >
            {triggerLabel}
          </span>
        </div>
      </div>

      {/* Expanded body */}
      {isExpanded && (
        <div ref={expandedBodyRef} className="px-[14px] pb-[12px]">
          {/* Description */}
          <p
            className="font-mono"
            style={{ fontSize: "12px", color: "#ffffff", lineHeight: 1.6, marginBottom: "10px" }}
          >
            {suggestion.description}
          </p>

          {/* Prompt preview */}
          <div
            style={{
              background: "#111",
              border: "1px solid #242424",
              borderRadius: "4px",
              padding: "8px 10px",
              marginBottom: "10px",
            }}
          >
            <p
              className="font-mono uppercase tracking-[0.1em]"
              style={{ fontSize: "11px", color: "#555", margin: "0 0 4px" }}
            >
              Prompt
            </p>
            <p
              className="font-mono"
              style={{
                fontSize: "11px",
                color: "#ffffff",
                lineHeight: 1.5,
                fontStyle: "italic",
                margin: 0,
              }}
            >
              {truncatedPrompt}
            </p>
          </div>

          {/* Action bar */}
          <div className="flex items-center" style={{ gap: "6px" }}>
            {suggestion.actions.includes("open_cowork") && (
              <button
                onClick={handleOpen}
                className="font-mono font-bold uppercase tracking-[0.08em] flex-1 transition-colors"
                style={{
                  fontSize: "11px",
                  padding: "6px 10px",
                  borderRadius: "3px",
                  border: "none",
                  cursor: "pointer",
                  background: openConfirmed ? "#22c55e" : openHovered ? "#ffe033" : "#f5c200",
                  color: "#000",
                }}
                onMouseEnter={() => setOpenHovered(true)}
                onMouseLeave={() => setOpenHovered(false)}
              >
                {openConfirmed ? "✓ Opened" : "Open Cowork"}
              </button>
            )}

            {suggestion.actions.includes("copy_prompt") && (
              <button
                onClick={handleCopy}
                className="font-mono font-bold uppercase tracking-[0.08em] flex-1 transition-colors"
                style={{
                  fontSize: "11px",
                  padding: "6px 10px",
                  borderRadius: "3px",
                  cursor: "pointer",
                  background: "transparent",
                  color: copyConfirmed ? "#22c55e" : "#ffffff",
                  border: copyConfirmed ? "1px solid #22c55e" : copyHovered ? "1px solid #555" : "1px solid #2a2a2a",
                }}
                onMouseEnter={() => setCopyHovered(true)}
                onMouseLeave={() => setCopyHovered(false)}
              >
                {copyConfirmed ? "✓ Copied" : "Copy Prompt"}
              </button>
            )}

            <button
              onClick={() => setShowDismissSheet(true)}
              className="font-mono shrink-0"
              style={{
                fontSize: "13px",
                padding: "5px 8px",
                borderRadius: "3px",
                cursor: "pointer",
                background: "transparent",
                color: "#fff",
                border: "1px solid #222",
              }}
            >
              ×
            </button>
          </div>
        </div>
      )}

      {/* Dismiss / snooze sheet */}
      {showDismissSheet && (
        <div
          className="absolute inset-0 flex items-end"
          style={{ background: "rgba(0,0,0,0.85)" }}
        >
          <div
            className="w-full"
            style={{
              background: "#1a1a1a",
              borderTop: "1px solid #2a2a2a",
              padding: "14px",
            }}
          >
            <p
              className="font-mono uppercase tracking-[0.1em]"
              style={{ fontSize: "11px", color: "#888", marginBottom: "8px" }}
            >
              Dismiss or snooze
            </p>
            <div className="flex flex-col" style={{ gap: "3px" }}>
              <button
                onClick={() => handleSnooze(new Date(Date.now() + 3600 * 1000).toISOString())}
                className="font-mono text-left w-full transition-colors"
                style={{
                  fontSize: "13px",
                  color: "#aaa",
                  background: "#111",
                  border: snooze1hHovered ? "1px solid #444" : "1px solid #222",
                  borderRadius: "3px",
                  padding: "9px 12px",
                  cursor: "pointer",
                }}
                onMouseEnter={() => setSnooze1hHovered(true)}
                onMouseLeave={() => setSnooze1hHovered(false)}
              >
                Snooze 1 hour
              </button>
              <button
                onClick={() => handleSnooze(tomorrowAt9am())}
                className="font-mono text-left w-full transition-colors"
                style={{
                  fontSize: "13px",
                  color: "#aaa",
                  background: "#111",
                  border: snoozeTomorrowHovered ? "1px solid #444" : "1px solid #222",
                  borderRadius: "3px",
                  padding: "9px 12px",
                  cursor: "pointer",
                }}
                onMouseEnter={() => setSnoozeTomorrowHovered(true)}
                onMouseLeave={() => setSnoozeTomorrowHovered(false)}
              >
                Snooze until tomorrow
              </button>
              <button
                onClick={handleDismiss}
                className="font-mono text-left w-full transition-colors"
                style={{
                  fontSize: "13px",
                  color: "#ef4444",
                  background: dismissPermHovered ? "#1a0505" : "#111",
                  border: dismissPermHovered ? "1px solid #ef4444" : "1px solid #222",
                  borderRadius: "3px",
                  padding: "9px 12px",
                  cursor: "pointer",
                }}
                onMouseEnter={() => setDismissPermHovered(true)}
                onMouseLeave={() => setDismissPermHovered(false)}
              >
                Dismiss permanently
              </button>
            </div>
            <button
              onClick={() => setShowDismissSheet(false)}
              className="font-mono uppercase w-full text-center transition-colors"
              style={{
                fontSize: "11px",
                color: cancelHovered ? "#888" : "#555",
                background: "none",
                border: "none",
                cursor: "pointer",
                marginTop: "8px",
              }}
              onMouseEnter={() => setCancelHovered(true)}
              onMouseLeave={() => setCancelHovered(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
