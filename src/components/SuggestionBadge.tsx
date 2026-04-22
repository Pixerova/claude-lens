import React from "react";

interface SuggestionBadgeProps {
  count: number;
  onView: () => void;
}

export const SuggestionBadge: React.FC<SuggestionBadgeProps> = ({ count, onView }) => {
  if (count === 0) return null;

  return (
    <div
      className="flex items-center justify-between px-[14px] py-[10px]"
      style={{ borderTop: "1px solid #222", background: "#131313" }}
    >
      <div className="flex items-center gap-[7px]">
        <div
          className="rounded-full shrink-0"
          style={{ width: "7px", height: "7px", background: "#f5c200" }}
        />
        <span className="font-mono" style={{ fontSize: "10px", color: "#ffffff" }}>
          {count === 1 ? "1 suggestion ready" : `${count} suggestions ready`}
        </span>
      </div>
      <button
        onClick={onView}
        className="font-mono font-bold uppercase tracking-[0.1em] transition-colors"
        style={{
          fontSize: "9px",
          background: "#f5c200",
          color: "#000",
          border: "none",
          borderRadius: "4px",
          padding: "5px 10px",
          cursor: "pointer",
        }}
        onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "#ffe033"}
        onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "#f5c200"}
      >
        VIEW →
      </button>
    </div>
  );
};
