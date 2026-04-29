/**
 * Onboarding.tsx — First-launch setup flow for Claude Lens.
 *
 * Shown once, before the main widget, when onboardingComplete is absent from
 * ~/.claudelens/config.json. Two steps:
 *
 *   Step 1 — Keychain access:
 *     Explain what the app needs and why, then let the user grant access.
 *     On success, advance to Step 2. On failure, offer a Retry path.
 *
 *   Step 2 — Ready:
 *     Show the first live plan reading fetched immediately on entry.
 *     One button completes onboarding and opens the main widget.
 */

import React, { useState, useEffect, useCallback } from "react";
import { api } from "../lib/api";
import type { UsageCurrent } from "../lib/api";

// ── Small helpers ─────────────────────────────────────────────────────────────

const fmt = (pct: number) => `${Math.round(pct * 100)}%`;

type Step = "keychain" | "ready";
type KeychainState = "idle" | "loading" | "success" | "error";

// ── Step 1: Keychain access ───────────────────────────────────────────────────

interface KeychainStepProps {
  onSuccess: () => void;
}

const KeychainStep: React.FC<KeychainStepProps> = ({ onSuccess }) => {
  const [state, setState] = useState<KeychainState>("idle");

  const handleGrant = useCallback(async () => {
    setState("loading");
    try {
      const status = await api.getAuthStatus();
      if (status.authenticated) {
        setState("success");
        // Short pause so the success state is visible, then advance.
        setTimeout(onSuccess, 600);
      } else {
        setState("error");
      }
    } catch {
      setState("error");
    }
  }, [onSuccess]);

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Icon */}
      <div className="flex justify-center">
        <div className="w-14 h-14 rounded-2xl bg-[#1a1a2e] border border-white/10 flex items-center justify-center">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#7dd3fc" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
            <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
          </svg>
        </div>
      </div>

      {/* Heading */}
      <div className="text-center">
        <p className="text-[15px] font-bold text-white tracking-[-0.01em]">
          Keychain Access
        </p>
        <p className="font-mono text-[10px] text-white/50 mt-1 leading-relaxed">
          Step 1 of 2
        </p>
      </div>

      {/* Explanation */}
      <p className="text-[11px] text-white/70 leading-relaxed text-center px-1">
        Claude Lens reads your plan limits directly from the Anthropic API using
        the OAuth token that Claude Code already stored in your macOS Keychain.
        No passwords, no sign-in — just a one-time permission prompt from macOS.
      </p>

      {/* Error note */}
      {state === "error" && (
        <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-[rgba(255,107,107,0.08)] border border-[rgba(255,107,107,0.25)]">
          <span className="w-[6px] h-[6px] rounded-full bg-[#ff6b6b] shrink-0 mt-[4px]" />
          <p className="font-mono text-[9px] text-[#ff6b6b] leading-relaxed">
            Could not read the token. Make sure Claude Code is installed and you
            are logged in. The widget will use cached data until access is granted.
          </p>
        </div>
      )}

      {/* CTA */}
      {state === "success" ? (
        <div className="flex items-center justify-center gap-2 py-[10px]">
          <span className="w-[8px] h-[8px] rounded-full bg-[#4ade80]" />
          <span className="font-mono text-[11px] font-bold text-[#4ade80]">Access granted</span>
        </div>
      ) : (
        <button
          onClick={handleGrant}
          disabled={state === "loading"}
          className="w-full py-[10px] rounded-[9px] font-mono text-[11px] font-bold tracking-[0.06em] text-white bg-[#1e3a5f] border border-[#2979ff]/40 hover:bg-[#244876] transition-colors disabled:opacity-50 cursor-pointer"
        >
          {state === "loading" ? "Checking…" : state === "error" ? "Retry" : "Grant Access"}
        </button>
      )}

      {/* Skip note */}
      {(state === "idle" || state === "error") && (
        <p className="text-center font-mono text-[9px] text-white/30 leading-relaxed">
          If access is denied, the widget will still work using cached data.
        </p>
      )}
    </div>
  );
};

// ── Step 2: Ready ─────────────────────────────────────────────────────────────

interface ReadyStepProps {
  onComplete: () => void;
}

const ReadyStep: React.FC<ReadyStepProps> = ({ onComplete }) => {
  const [usage, setUsage] = useState<UsageCurrent | null>(null);
  const [sessionCount, setSessionCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [completing, setCompleting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const fetch = async () => {
      try {
        const [u, stats] = await Promise.all([
          api.getUsageCurrent(),
          api.getSessionStats(7),
        ]);
        if (!cancelled) {
          setUsage(u);
          setSessionCount(stats.sessionCount);
        }
      } catch {
        // Non-fatal — widget will still open
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetch();
    return () => { cancelled = true; };
  }, []);

  const handleOpen = useCallback(async () => {
    setCompleting(true);
    try {
      await api.completeOnboarding();
    } catch {
      // If the write fails, proceed anyway — the flag will be retried on next launch
    }
    onComplete();
  }, [onComplete]);

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Icon */}
      <div className="flex justify-center">
        <div className="w-14 h-14 rounded-2xl bg-[#0e1f0e] border border-[#4ade80]/20 flex items-center justify-center">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#4ade80" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </div>
      </div>

      {/* Heading */}
      <div className="text-center">
        <p className="text-[15px] font-bold text-white tracking-[-0.01em]">
          All set
        </p>
        <p className="font-mono text-[10px] text-white/50 mt-1 leading-relaxed">
          Step 2 of 2 — First live reading
        </p>
      </div>

      {/* Live reading */}
      {loading ? (
        <div className="grid grid-cols-2 gap-2">
          {[0, 1].map((i) => (
            <div
              key={i}
              className="rounded-[9px] h-[60px] bg-white/[0.07] animate-pulse"
              style={{ animationDelay: `${i * 0.1}s` }}
            />
          ))}
        </div>
      ) : usage ? (
        <div className="grid grid-cols-2 gap-2">
          {/* Session tile */}
          <div className="rounded-[9px] bg-white/[0.06] border border-white/[0.08] p-3 flex flex-col gap-1">
            <p className="font-mono text-[8px] font-bold text-white/50 uppercase tracking-[0.08em]">Session</p>
            <p className="font-mono text-[22px] font-black text-white leading-none">
              {fmt(usage.sessionPct)}
            </p>
            <p className="font-mono text-[8px] text-white/40">used</p>
          </div>
          {/* Weekly tile */}
          <div className="rounded-[9px] bg-white/[0.06] border border-white/[0.08] p-3 flex flex-col gap-1">
            <p className="font-mono text-[8px] font-bold text-white/50 uppercase tracking-[0.08em]">Weekly</p>
            <p className="font-mono text-[22px] font-black text-white leading-none">
              {fmt(usage.weeklyPct)}
            </p>
            <p className="font-mono text-[8px] text-white/40">used</p>
          </div>
        </div>
      ) : (
        <p className="font-mono text-[10px] text-white/40 text-center">
          Usage data will appear once the sidecar is running.
        </p>
      )}

      {/* Session count */}
      {sessionCount !== null && sessionCount > 0 && (
        <p className="font-mono text-[10px] text-white/50 text-center">
          {sessionCount} local session{sessionCount !== 1 ? "s" : ""} found from the last 7 days
        </p>
      )}

      {/* CTA */}
      <button
        onClick={handleOpen}
        disabled={completing}
        className="w-full py-[10px] rounded-[9px] font-mono text-[11px] font-bold tracking-[0.06em] text-white bg-[#1e3a5f] border border-[#2979ff]/40 hover:bg-[#244876] transition-colors disabled:opacity-50 cursor-pointer"
      >
        {completing ? "Opening…" : "Open Claude Lens →"}
      </button>
    </div>
  );
};

// ── Onboarding shell ──────────────────────────────────────────────────────────

interface OnboardingProps {
  onComplete: () => void;
}

const Onboarding: React.FC<OnboardingProps> = ({ onComplete }) => {
  const [step, setStep] = useState<Step>("keychain");

  return (
    <div className="min-h-screen flex items-start justify-center p-2 bg-transparent">
      <div className="w-full rounded-[14px] bg-app-bg border border-white/[0.09] shadow-2xl shadow-black/60 overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-[7px] px-[11px] py-[9px] border-b border-white/[0.07]">
          <img src="/app-icon.png" width={38} height={38} className="shrink-0 rounded-[8px]" alt="" />
          <span className="text-[12px] font-semibold text-white flex-1 tracking-[-0.01em]">
            claude-lens
          </span>
          <span className="font-mono text-[9px] text-white/30">setup</span>
        </div>

        {/* Step content */}
        {step === "keychain" ? (
          <KeychainStep onSuccess={() => setStep("ready")} />
        ) : (
          <ReadyStep onComplete={onComplete} />
        )}
      </div>
    </div>
  );
};

export default Onboarding;
