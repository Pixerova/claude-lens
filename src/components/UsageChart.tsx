/**
 * UsageChart.tsx — Stacked bar chart of daily cost by source (7-day view).
 *
 * Uses Recharts BarChart. Code sessions = primary blue, Cowork = purple.
 * Shown only in expanded view.
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
import { type ChartPoint } from "../lib/api";

interface UsageChartProps {
  data: ChartPoint[];
}

interface DayEntry {
  day: string;       // "Mon", "Tue", etc.
  code: number;
  cowork: number;
}

const PRIMARY  = "#4B9EFF";
const PURPLE   = "#A78BFA";
const GRAY_500 = "#6b7280";
const GRAY_700 = "#374151";

function shortDay(isoDay: string): string {
  const d = new Date(isoDay + "T12:00:00");   // noon avoids TZ day-flip
  return d.toLocaleDateString("en-US", { weekday: "short" });
}

export const UsageChart: React.FC<UsageChartProps> = ({ data }) => {
  const chartData = useMemo<DayEntry[]>(() => {
    // Build a map: day → { code, cowork }
    const map = new Map<string, DayEntry>();
    data.forEach((pt) => {
      if (!map.has(pt.day)) {
        map.set(pt.day, { day: shortDay(pt.day), code: 0, cowork: 0 });
      }
      const entry = map.get(pt.day)!;
      if (pt.source === "code")   entry.code   += pt.costUsd;
      if (pt.source === "cowork") entry.cowork += pt.costUsd;
    });
    // Sort by date ascending
    return [...map.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([, v]) => v);
  }, [data]);

  if (chartData.length === 0) {
    return (
      <p className="text-center text-xs text-gray-500 py-4">
        No session cost data yet.
      </p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={90}>
      <BarChart data={chartData} barSize={10} barCategoryGap="30%">
        <XAxis
          dataKey="day"
          tick={{ fill: GRAY_500, fontSize: 9 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis hide />
        <Tooltip
          contentStyle={{
            background: "#242424",
            border: `1px solid ${GRAY_700}`,
            borderRadius: 6,
            fontSize: 11,
            color: "#e5e7eb",
          }}
          formatter={(value: number, name: string) => [
            `$${value.toFixed(3)}`,
            name.charAt(0).toUpperCase() + name.slice(1),
          ]}
          cursor={{ fill: "rgba(255,255,255,0.04)" }}
        />
        <Bar dataKey="code"   stackId="a" fill={PRIMARY} radius={[0, 0, 2, 2]} name="Code" />
        <Bar dataKey="cowork" stackId="a" fill={PURPLE}  radius={[2, 2, 0, 0]} name="Cowork" />
      </BarChart>
    </ResponsiveContainer>
  );
};
