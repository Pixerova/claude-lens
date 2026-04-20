/**
 * SuggestionBadge.tsx — Footer bar shown at the bottom of the expanded view.
 *
 * Stub for M5 (Suggestion Engine). Hidden when count is 0.
 * In expanded view: [bulb icon] "N suggestions ready"  [VIEW →]
 */

import React from "react";

interface SuggestionBadgeProps {
  count: number;
  onView: () => void;
}

export const SuggestionBadge: React.FC<SuggestionBadgeProps> = ({ count, onView }) => {
  if (count === 0) return null;

  return (
    <div className="flex items-center justify-between border-t border-white/[0.08] bg-white/[0.02] px-3 py-2">
      <div className="flex items-center gap-2">
        <div className="w-[26px] h-[26px] rounded-full bg-[rgba(255,214,0,0.12)] border border-[rgba(255,214,0,0.35)] flex items-center justify-center shrink-0">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ffd600" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 21h6"/>
            <path d="M12 3a6 6 0 0 1 6 6c0 2.22-1.2 4.16-3 5.2V17a1 1 0 0 1-1 1H10a1 1 0 0 1-1-1v-2.8C7.2 13.16 6 11.22 6 9a6 6 0 0 1 6-6z"/>
          </svg>
        </div>
        <span className="text-[11px] font-semibold text-white">
          {count === 1 ? "1 suggestion ready" : `${count} suggestions ready`}
        </span>
      </div>
      <button
        onClick={onView}
        className="font-mono text-[9px] font-bold tracking-[0.05em] text-[#6eb0ff] bg-[rgba(0,114,255,0.1)] border border-[rgba(0,114,255,0.3)] rounded px-[9px] py-[3px] cursor-pointer hover:bg-[rgba(0,114,255,0.18)] transition-colors"
      >
        VIEW →
      </button>
    </div>
  );
};
