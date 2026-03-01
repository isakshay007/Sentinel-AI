"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api, type SafetyReportResponse } from "@/lib/api";

export default function SafetyPage() {
  const [data, setData] = useState<SafetyReportResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getSafetyReport().then(setData).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px] text-muted-foreground text-[15px]">
        Loading...
      </div>
    );
  }

  if (data?.error) {
    return (
      <div className="space-y-6">
        <h1 className="text-page-title">Safety</h1>
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-5 text-destructive shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
          {data.error}
        </div>
      </div>
    );
  }

  const score = data?.composite_safety_score ?? 0;
  const allowed = data?.deployment_allowed ?? false;
  const threshold = data?.threshold ?? 85;
  const categories = data?.category_scores ?? {};
  const guardrails = data?.guardrails ?? { guardrails: {}, active: 0, total: 0, score: 0 };

  return (
    <div className="space-y-8" style={{ gap: "var(--spacing-section, 32px)" }}>
      <h1 className="text-page-title">Safety</h1>

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="shadow-[0_1px_2px_rgba(0,0,0,0.05)] border-[#E5E7EB]">
          <CardHeader>
            <CardTitle>Composite Safety Score</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center gap-6 flex-wrap p-5">
            <div className="relative w-40 h-40 shrink-0">
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
                  strokeDasharray={`${score}, 100`}
                  strokeLinecap="round"
                  fill="none"
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                />
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-3xl font-bold">
                {score.toFixed(1)}
              </span>
            </div>
            <div className="flex flex-col justify-center gap-3">
              <Badge
                variant={allowed ? "default" : "destructive"}
                className={`w-fit text-[13px] font-semibold px-3 py-1 ${
                  allowed ? "bg-emerald-600 hover:bg-emerald-600" : ""
                }`}
              >
                {allowed ? "DEPLOYMENT ALLOWED" : "DEPLOYMENT BLOCKED"}
              </Badge>
              <p className="text-[15px] text-muted-foreground">
                Threshold: <span className="font-semibold text-foreground">{threshold}</span>
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-[0_1px_2px_rgba(0,0,0,0.05)] border-[#E5E7EB]">
          <CardHeader>
            <CardTitle>Category Scores</CardTitle>
          </CardHeader>
          <CardContent className="p-5">
            <div className="grid grid-cols-2 gap-4">
              {Object.entries(categories).map(([name, val]) => (
                <div key={name} className="p-4 rounded-lg border border-[#E5E7EB] space-y-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="text-[14px] font-medium capitalize">{name.replace(/_/g, " ")}</p>
                    <p
                      className={`text-base font-bold shrink-0 ${
                        (val ?? 0) >= 70 ? "text-emerald-600" : "text-red-600"
                      }`}
                    >
                      {(val ?? 0).toFixed(0)}
                    </p>
                  </div>
                  <div className="h-2.5 bg-muted rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full transition-all"
                      style={{ width: `${Math.min(val ?? 0, 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="shadow-[0_1px_2px_rgba(0,0,0,0.05)] border-[#E5E7EB]">
        <CardHeader>
          <CardTitle>Guardrails ({guardrails.active}/{guardrails.total} active)</CardTitle>
        </CardHeader>
        <CardContent className="p-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {Object.entries(guardrails.guardrails || {}).map(([name, g]) => (
              <div
                key={name}
                className="p-4 rounded-lg border border-[#E5E7EB] space-y-2 transition-shadow hover:shadow-md"
              >
                <div className="flex items-center justify-between">
                  <p className="font-medium text-[15px] capitalize">{name.replace(/_/g, " ")}</p>
                  <Badge variant={g.status === "active" ? "default" : "secondary"} className="text-[13px]">
                    {g.status}
                  </Badge>
                </div>
                <p className="text-[14px] text-muted-foreground line-clamp-2 leading-relaxed">
                  {g.description}
                </p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
