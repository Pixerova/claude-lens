/**
 * SuggestionBadge.tsx — Compact badge shown in the collapsed widget.
 *
 * Stub for M5 (Suggestion Engine). Currently always shows 0 suggestions
 * and is ready to wire up once the /suggestions endpoint exists.
 *
 * In compact view: "💡 N suggestions ready  [View]"
 * Hidden when count is 0 and there's nothing to show.
 */

import React from "react";

interface SuggestionBadgeProps {
  count: number;
  onView: () => void;   // expands the widget to show full panel
}

export const SuggestionBadge: React.FC<SuggestionBadgeProps> = ({ count, onView }) => {
  if (count === 0) return null;

  return (
    <div className="flex items-center justify-between px-4 py-2.5 border-t border-white/8 bg-white/3">
      <div className="flex items-center gap-2">
        <span className="text-sm leading-none">💡</span>
        <span className="text-xs text-gray-300">
          {count === 1 ? "1 suggestion ready" : `${count} suggestions ready`}
        </span>
      </div>
      <button
        onClick={onView}
        className="text-[11px] font-medium text-primary hover:text-blue-300 transition-colors px-2 py-1 rounded hover:bg-primary/10"
      >
        View
      </button>
    </div>
  );
};
