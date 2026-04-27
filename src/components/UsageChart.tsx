/**
 * UsageChart.tsx — Stacked bar chart for daily metrics by source (7-day view).
 *
 * Generic over the value being charted. Data is passed as a flat array of
 * { day, source, value } points; the chart aggregates into stacked bars.
 *
 * unit="percent"  — values are already normalised to % of 7-day total (0–100).
 *                   Tooltip shows "X.X%". Bars are always visible regardless of
 *                   absolute cost magnitude (important for MAX plan users).
 * unit="cost"     — values are USD; tooltip shows "$X.XXX".
 */

import React, { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export interface ChartDataPoint {
  day: string;              // YYYY-MM-DD
  source: "code" | "cowork";
  value: number;            // costUsd or durationSec depending on unit
}

interface UsageChartProps {
  data: ChartDataPoint[];
  unit: "cost" | "percent";
  emptyLabel?: string;
}

interface DayEntry {
  day: string;   // "Mon", "Tue", etc.
  code: number;
  cowork: number;
}

const CODE_BLUE     = "#2979ff";
const COWORK_PURPLE = "#7c5cbf";
const AXIS_COLOR    = "rgba(255,255,255,0.4)";
const TOOLTIP_BG    = "#1a1a1c";
const TOOLTIP_BORDER = "#374151";

function shortDay(isoDay: string): string {
  const d = new Date(isoDay + "T12:00:00");  // noon avoids TZ day-flip
  return d.toLocaleDateString("en-US", { weekday: "short" });
}

function localIso(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export const UsageChart: React.FC<UsageChartProps> = ({ data, unit, emptyLabel }) => {
  const chartData = useMemo<DayEntry[]>(() => {
    // Build a 7-day scaffold in local time so zero-usage days always render.
    const today = new Date();
    const days: string[] = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(d.getDate() - i);
      days.push(localIso(d));
    }
    const map = new Map<string, DayEntry>(
      days.map((iso) => [iso, { day: shortDay(iso), code: 0, cowork: 0 }])
    );
    data.forEach((pt) => {
      const entry = map.get(pt.day);
      if (!entry) return;
      if (pt.source === "code")   entry.code   += pt.value;
      if (pt.source === "cowork") entry.cowork += pt.value;
    });
    return days.map((iso) => map.get(iso)!);
  }, [data]);

  if (chartData.length === 0) {
    return (
      <p className="font-mono text-center text-[10px] text-white/30 py-4">
        {emptyLabel ?? "No data yet."}
      </p>
    );
  }

  const tooltipFormatter = (value: number, name: string): [string, string] => {
    const label = name.charAt(0).toUpperCase() + name.slice(1);
    const formatted = unit === "cost"
      ? `$${value.toFixed(3)}`
      : `${value.toFixed(1)}%`;
    return [formatted, label];
  };

  return (
    <ResponsiveContainer width="100%" height={56}>
      <BarChart data={chartData} barCategoryGap="20%">
        <XAxis
          dataKey="day"
          tick={{ fill: AXIS_COLOR, fontSize: 10 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis hide />
        <Tooltip
          contentStyle={{
            background: TOOLTIP_BG,
            border: `1px solid ${TOOLTIP_BORDER}`,
            borderRadius: 6,
            fontSize: 11,
            color: "#ffffff",
          }}
          formatter={tooltipFormatter}
          cursor={{ fill: "rgba(255,255,255,0.04)" }}
        />
        <Bar dataKey="code"   stackId="a" fill={CODE_BLUE}     radius={[0, 0, 2, 2]} name="Code" />
        <Bar dataKey="cowork" stackId="a" fill={COWORK_PURPLE} radius={[2, 2, 0, 0]} name="Cowork" />
      </BarChart>
    </ResponsiveContainer>
  );
};
