/**
 * StaleIndicator.tsx — Banner shown when usage data is stale.
 *
 * Displayed below the usage tiles in both collapsed and expanded views.
 */

import React from "react";

interface StaleIndicatorProps {
  isStale: boolean;
  recordedAt?: string;  // ISO 8601 — shown as "last updated HH:MM"
  error?: string | null;
}

export const StaleIndicator: React.FC<StaleIndicatorProps> = ({
  isStale,
  recordedAt,
  error,
}) => {
  if (!isStale && !error) return null;

  let label = "Data stale";
  if (error) {
    label = "Sidecar unreachable";
  } else if (recordedAt) {
    const t = new Date(recordedAt).toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
    });
    label = `Data stale · last updated ${t}`;
  }

  return (
    <div className="flex items-center gap-[6px] mx-[10px] my-2 px-[9px] py-[5px] rounded-[6px] bg-[rgba(255,210,0,0.08)] border border-[rgba(255,210,0,0.20)]">
      <span className="w-[6px] h-[6px] rounded-full bg-[#ffd200] animate-pulse shrink-0" />
      <span className="font-mono text-[9px] font-semibold text-[#ffd200] leading-none">{label}</span>
    </div>
  );
};
