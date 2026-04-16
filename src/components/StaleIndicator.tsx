/**
 * StaleIndicator.tsx — Subtle badge shown when usage data is stale.
 *
 * Shown when `isStale` is true (sidecar hasn't been able to reach
 * the API recently) or when the sidecar itself is unreachable.
 */

import React from "react";

interface StaleIndicatorProps {
  isStale: boolean;
  recordedAt?: string;  // ISO 8601 — shown as "as of HH:MM"
  error?: string | null;
}

export const StaleIndicator: React.FC<StaleIndicatorProps> = ({
  isStale,
  recordedAt,
  error,
}) => {
  if (!isStale && !error) return null;

  let label = "Data may be stale";
  if (error) {
    label = "Sidecar unreachable";
  } else if (recordedAt) {
    const t = new Date(recordedAt).toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
    });
    label = `Last updated ${t}`;
  }

  return (
    <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber/10 border border-amber/20 w-fit">
      <span className="w-1.5 h-1.5 rounded-full bg-amber animate-pulse" />
      <span className="text-[10px] text-amber leading-none">{label}</span>
    </div>
  );
};
