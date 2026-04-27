import React from "react";

export const SleepIndicator: React.FC = () => (
  <div className="flex items-center gap-[6px] mx-[10px] my-2 px-[9px] py-[5px] rounded-[6px] bg-[rgba(125,211,252,0.08)] border border-[rgba(125,211,252,0.20)]">
    <span className="w-[6px] h-[6px] rounded-full bg-[#7dd3fc] animate-pulse shrink-0" />
    <span className="font-mono text-[9px] font-semibold text-[#7dd3fc] leading-none">
      sleeping · will resume polling on new activity
    </span>
  </div>
);
