"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type EvalResultsResponse } from "@/lib/api";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

const BAR_COLORS = ["#6366f1", "#8b5cf6", "#ec4899", "#10B981"];

export default function EvaluationsPage() {
  const [data, setData] = useState<EvalResultsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getEvalResults().then(setData).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px] text-muted-foreground text-[15px]">
        Loading...
      </div>
    );
  }

  const latest = data?.evaluations?.[0];
  const results = latest?.results ?? {};
  const scenarios = Object.keys(results);
  const metricNames = new Set<string>();
  scenarios.forEach((s) => {
    const r = results[s as keyof typeof results];
    if (r && typeof r === "object" && "scores" in r && r.scores) {
      Object.keys(r.scores as Record<string, number>).forEach((m) => metricNames.add(m));
    }
  });
  const metrics = Array.from(metricNames);

  const chartData = metrics.map((m) => {
    const row: Record<string, string | number> = { metric: m.replace(/_/g, " ") };
    scenarios.forEach((s) => {
      const r = results[s as keyof typeof results];
      const scores = r && typeof r === "object" && "scores" in r ? (r.scores as Record<string, number>) : {};
      row[s] = scores[m] ?? 0;
    });
    return row;
  });

  const allScores: { metric: string; avg: number }[] = metrics.map((m) => {
    let sum = 0;
    let count = 0;
    scenarios.forEach((s) => {
      const r = results[s as keyof typeof results];
      const scores = r && typeof r === "object" && "scores" in r ? (r.scores as Record<string, number>) : {};
      const v = scores[m];
      if (typeof v === "number") {
        sum += v;
        count++;
      }
    });
    return { metric: m.replace(/_/g, " "), avg: count ? sum / count : 0 };
  });
  const overallScore = allScores.length
    ? allScores.reduce((a, b) => a + b.avg, 0) / allScores.length
    : 0;

  const strengths = allScores.filter((x) => x.avg >= 0.7).map((x) => x.metric);
  const weakAreas = allScores.filter((x) => x.avg < 0.5).map((x) => x.metric);

  return (
    <div className="space-y-8" style={{ gap: "var(--spacing-section, 32px)" }}>
      <h1 className="text-page-title">Evaluations</h1>

      <Card className="shadow-[0_1px_2px_rgba(0,0,0,0.05)] border-[#E5E7EB]">
        <CardHeader>
          <CardTitle>Overall Score</CardTitle>
        </CardHeader>
        <CardContent className="p-5">
          <div className="flex items-center gap-6">
            <div className="relative w-28 h-28">
              <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
                <path
                  className="text-muted"
                  stroke="currentColor"
                  strokeWidth="3"
                  fill="none"
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                />
                <path
                  className="text-primary"
                  stroke="currentColor"
                  strokeWidth="3"
                  strokeDasharray={`${overallScore * 100}, 100`}
                  strokeLinecap="round"
                  fill="none"
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                />
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-xl font-bold">
                {(overallScore * 100).toFixed(0)}%
              </span>
            </div>
            <div className="text-[15px] text-muted-foreground">
              Based on {allScores.length} metrics across {scenarios.length}{" "}
              {scenarios.length === 1 ? "scenario" : "scenarios"}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Metric Summary Strip */}
      {(strengths.length > 0 || weakAreas.length > 0) && (
        <Card className="shadow-[0_1px_2px_rgba(0,0,0,0.05)] border-[#E5E7EB]">
          <CardContent className="p-5">
            <div className="grid gap-6 md:grid-cols-2">
              <div>
                <p className="text-[13px] font-semibold uppercase tracking-wide text-emerald-600 mb-2">
                  Strengths
                </p>
                <p className="text-[15px] text-muted-foreground">
                  {strengths.length > 0 ? strengths.join(", ") : "—"}
                </p>
              </div>
              <div>
                <p className="text-[13px] font-semibold uppercase tracking-wide text-amber-600 mb-2">
                  Weak Areas
                </p>
                <p className="text-[15px] text-muted-foreground">
                  {weakAreas.length > 0 ? weakAreas.join(", ") : "None identified"}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {chartData.length > 0 && (
        <Card className="shadow-[0_1px_2px_rgba(0,0,0,0.05)] border-[#E5E7EB]">
          <CardHeader>
            <CardTitle>Scores by Metric</CardTitle>
          </CardHeader>
          <CardContent className="p-5">
            <div className="h-[480px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={chartData}
                  layout="vertical"
                  margin={{ top: 20, right: 100, left: 140, bottom: 20 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" vertical={false} />
                  <XAxis type="number" domain={[0, 1]} tick={{ fontSize: 14 }} />
                  <YAxis
                    type="category"
                    dataKey="metric"
                    width={130}
                    tick={{ fontSize: 14 }}
                  />
                  <Tooltip />
                  <Legend />
                  {scenarios.map((s, i) => (
                    <Bar
                      key={s}
                      dataKey={s}
                      fill={BAR_COLORS[i % BAR_COLORS.length]}
                      radius={[0, 4, 4, 0]}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="shadow-[0_1px_2px_rgba(0,0,0,0.05)] border-[#E5E7EB]">
        <CardHeader>
          <CardTitle>Full Results Table</CardTitle>
        </CardHeader>
        <CardContent className="p-5">
          <div className="overflow-x-auto">
            <table className="w-full text-[15px]">
              <thead>
                <tr className="border-b border-[#E5E7EB]">
                  <th className="text-left py-3 font-semibold">Metric</th>
                  {scenarios.map((s) => (
                    <th key={s} className="text-right py-3 font-semibold">
                      {s.replace(/_/g, " ")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {metrics.map((m) => (
                  <tr key={m} className="border-b border-[#E5E7EB]">
                    <td className="py-3">{m.replace(/_/g, " ")}</td>
                    {scenarios.map((s) => {
                      const r = results[s as keyof typeof results];
                      const scores =
                        r && typeof r === "object" && "scores" in r
                          ? (r.scores as Record<string, number>)
                          : {};
                      const v = scores[m] ?? 0;
                      const color =
                        v >= 0.7 ? "text-emerald-600" : v >= 0.5 ? "text-amber-600" : "text-red-600";
                      return (
                        <td key={s} className={`text-right py-3 font-medium ${color}`}>
                          {v.toFixed(2)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
