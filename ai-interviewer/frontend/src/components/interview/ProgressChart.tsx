"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ArrowRight, TrendingUp } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { WEAK_DIMENSION_THRESHOLD } from "@/lib/constants/scores";
import type { InterviewHistoryEntry } from "@/lib/storage/interviewHistory";

const DIMENSION_LABELS: Record<string, string> = {
  technical_depth: "技术深度",
  problem_solving: "问题解决",
  communication: "沟通表达",
  system_design: "系统设计",
  coding_quality: "代码质量",
  project_experience: "项目经验",
  product_thinking: "产品思维",
  customer_discovery: "客户发现",
};

type ChartPoint = {
  label: string;
  score: number;
};

export function ProgressChart({
  entries,
}: {
  entries: InterviewHistoryEntry[];
}) {
  const scoredEntries = useMemo(
    () =>
      entries
        .filter((entry) => typeof entry.overallScore === "number")
        .sort((a, b) => a.createdAt.localeCompare(b.createdAt)),
    [entries],
  );
  const dimensions = useMemo(() => {
    const ids = new Set<string>();
    for (const entry of scoredEntries) {
      for (const id of Object.keys(entry.dimensionScores ?? {})) {
        ids.add(id);
      }
    }
    return Array.from(ids).sort();
  }, [scoredEntries]);
  const [activeDimension, setActiveDimension] = useState<string>("overallScore");

  const chartData = useMemo<ChartPoint[]>(() => {
    return scoredEntries
      .map((entry) => {
        const raw =
          activeDimension === "overallScore"
            ? entry.overallScore
            : entry.dimensionScores?.[activeDimension];
        if (typeof raw !== "number") return null;
        return {
          label: new Date(entry.createdAt).toLocaleDateString(undefined, {
            month: "numeric",
            day: "numeric",
          }),
          score: Number(raw.toFixed(1)),
        };
      })
      .filter((point): point is ChartPoint => Boolean(point));
  }, [activeDimension, scoredEntries]);

  const latest = scoredEntries[scoredEntries.length - 1];
  const best = scoredEntries.reduce<InterviewHistoryEntry | null>((acc, entry) => {
    if (typeof entry.overallScore !== "number") return acc;
    if (!acc || entry.overallScore > (acc.overallScore ?? 0)) return entry;
    return acc;
  }, null);
  const recentFive = scoredEntries.slice(-5);
  const delta =
    recentFive.length >= 2 &&
    typeof recentFive[0].overallScore === "number" &&
    typeof recentFive[recentFive.length - 1].overallScore === "number"
      ? recentFive[recentFive.length - 1].overallScore! - recentFive[0].overallScore!
      : null;
  const weakPracticeHref = buildWeakPracticeHref(scoredEntries);

  return (
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <TrendingUp className="h-4 w-4 text-emerald-400" />
              进步趋势
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              看最近几场练习的分数变化和薄弱维度。
            </p>
          </div>
          {weakPracticeHref && (
            <Button asChild size="sm" className="gap-1.5 bg-emerald-600 text-white hover:bg-emerald-500">
              <Link href={weakPracticeHref}>
                针对薄弱点专项练习
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </Button>
          )}
        </div>

        <div className="grid gap-2 sm:grid-cols-3">
          <Stat label="最近一次" value={formatScore(latest?.overallScore)} />
          <Stat label="最高分" value={formatScore(best?.overallScore)} />
          <Stat label="近 5 场变化" value={formatDelta(delta)} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-1">
          <button
            type="button"
            onClick={() => setActiveDimension("overallScore")}
            className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
              activeDimension === "overallScore"
                ? "bg-emerald-500/15 text-emerald-300"
                : "bg-secondary/40 text-muted-foreground hover:text-foreground"
            }`}
          >
            总分
          </button>
          {dimensions.map((dimension) => (
            <button
              key={dimension}
              type="button"
              onClick={() => setActiveDimension(dimension)}
              className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                activeDimension === dimension
                  ? "bg-emerald-500/15 text-emerald-300"
                  : "bg-secondary/40 text-muted-foreground hover:text-foreground"
              }`}
            >
              {formatDimensionName(dimension)}
            </button>
          ))}
        </div>

        {chartData.length < 2 ? (
          <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            完成至少两场带评分的练习后，这里会出现趋势线。
          </div>
        ) : (
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.16} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={11} />
                <YAxis domain={[0, 10]} tickLine={false} axisLine={false} fontSize={11} />
                <Tooltip
                  cursor={{ strokeDasharray: "3 3" }}
                  formatter={(value) => [`${Number(value).toFixed(1)} / 10`, "分数"]}
                />
                {/*
                 * Threshold line so users can read "below this is weak"
                 * directly off the chart, in sync with
                 * ``buildWeakPracticeHref``'s filter (audit F5).
                 */}
                <ReferenceLine
                  y={WEAK_DIMENSION_THRESHOLD}
                  stroke="#f59e0b"
                  strokeDasharray="4 4"
                  strokeOpacity={0.5}
                  label={{
                    value: `达标线 ${WEAK_DIMENSION_THRESHOLD}`,
                    position: "insideTopRight",
                    fill: "#f59e0b",
                    fontSize: 10,
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="score"
                  stroke="#34d399"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  activeDot={{ r: 5 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card/50 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-lg font-semibold">{value}</p>
    </div>
  );
}

function formatScore(score: number | undefined): string {
  return typeof score === "number" ? `${score.toFixed(1)} / 10` : "暂无";
}

function formatDelta(delta: number | null): string {
  if (delta === null) return "暂无";
  if (Math.abs(delta) < 0.05) return "持平";
  return `${delta > 0 ? "+" : ""}${delta.toFixed(1)}`;
}

function formatDimensionName(id: string): string {
  return DIMENSION_LABELS[id] ?? id.replaceAll("_", " ");
}

function buildWeakPracticeHref(entries: InterviewHistoryEntry[]): string | null {
  const recent = entries.slice(-5);
  const buckets = new Map<string, { total: number; count: number }>();
  for (const entry of recent) {
    for (const [dimension, score] of Object.entries(entry.dimensionScores ?? {})) {
      if (score >= WEAK_DIMENSION_THRESHOLD) continue;
      const bucket = buckets.get(dimension) ?? { total: 0, count: 0 };
      bucket.total += score;
      bucket.count += 1;
      buckets.set(dimension, bucket);
    }
  }
  const focus = Array.from(buckets.entries())
    .sort((a, b) => a[1].total / a[1].count - b[1].total / b[1].count)
    .slice(0, 2)
    .map(([dimension]) => dimension);
  if (focus.length === 0) return null;
  const latest = recent[recent.length - 1];
  const params = new URLSearchParams({
    focus: focus.join(","),
    length: "short",
  });
  if (latest?.jdTitle) params.set("job_title", latest.jdTitle);
  if (latest?.jobLevel) params.set("job_level", latest.jobLevel);
  return `/interview/setup?${params.toString()}`;
}
