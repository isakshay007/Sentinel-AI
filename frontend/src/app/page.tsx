"use client";

import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { api, type DashboardStats, type ServiceHealthResponse, type Incident } from "@/lib/api";
import { usePipeline } from "@/contexts/pipeline-context";
import { useTerminalWindows } from "@/contexts/terminal-windows-context";
import {
  AlertTriangle,
  ClipboardList,
  Shield,
  TrendingUp,
  Activity,
  Brain,
  Swords,
  Zap,
  BarChart2,
} from "lucide-react";
import Link from "next/link";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const AGENTS = [
  { id: "watcher", name: "Watcher", icon: Activity, color: "text-blue-500" },
  { id: "diagnostician", name: "Diagnostician", icon: Brain, color: "text-purple-500" },
  { id: "strategist", name: "Strategist", icon: Swords, color: "text-amber-500" },
  { id: "executor", name: "Executor", icon: Zap, color: "text-emerald-500" },
];

function parseLastAction(reasoning: string | null): string {
  if (!reasoning) return "Idle";
  try {
    const o = JSON.parse(reasoning);
    if (typeof o === "object") {
      const s = o.summary || o.analysis?.[0];
      if (s) return String(s).slice(0, 40) + (String(s).length > 40 ? "…" : "");
    }
  } catch {
    return typeof reasoning === "string" ? reasoning.slice(0, 30) + "…" : "Idle";
  }
  return "Idle";
}

function KPICard({
  label,
  value,
  icon: Icon,
  tooltip,
}: {
  label: string;
  value: string | number;
  icon: React.ElementType;
  tooltip?: string;
}) {
  const card = (
    <Card className="shadow-[0_1px_2px_rgba(0,0,0,0.05)] border-[#E5E7EB]">
      <CardContent className="p-5">
        <p className="text-[13px] font-medium uppercase tracking-wide text-muted-foreground mb-1">
          {label}
        </p>
        <p className="text-[32px] font-semibold leading-none">{value}</p>
        <Icon className="h-5 w-5 text-muted-foreground mt-2 opacity-60" />
      </CardContent>
    </Card>
  );
  if (tooltip) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>{card}</TooltipTrigger>
        <TooltipContent>
          <p>{tooltip}</p>
        </TooltipContent>
      </Tooltip>
    );
  }
  return card;
}

export default function DashboardPage() {
  const { isRunning, result } = usePipeline();
  const { openAgentTerminal } = useTerminalWindows();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [services, setServices] = useState<ServiceHealthResponse | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [decisionsByAgent, setDecisionsByAgent] = useState<Record<string, { reasoning: string | null; created_at: string | null }>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshAll = () => {
    api.getStats().then(setStats).catch(() => {});
    api.getServiceHealth().then(setServices).catch(() => {});
    api.getIncidents("open").then((r) => setIncidents(r.incidents)).catch(() => {});
    api.getAgentDecisions(undefined, 20).then((r) => {
      const byAgent: Record<string, { reasoning: string | null; created_at: string | null }> = {};
      for (const d of r.decisions) {
        if (!byAgent[d.agent_name]) {
          byAgent[d.agent_name] = { reasoning: d.reasoning, created_at: d.created_at };
        }
      }
      setDecisionsByAgent(byAgent);
    }).catch(() => {});
  };

  useEffect(() => {
    Promise.all([
      api.getStats(),
      api.getServiceHealth(),
      api.getIncidents("open"),
      api.getAgentDecisions(undefined, 20),
    ])
      .then(([s, h, inc, dec]) => {
        setStats(s);
        setServices(h);
        setIncidents(inc.incidents);
        const byAgent: Record<string, { reasoning: string | null; created_at: string | null }> = {};
        for (const d of dec.decisions) {
          if (!byAgent[d.agent_name]) {
            byAgent[d.agent_name] = { reasoning: d.reasoning, created_at: d.created_at };
          }
        }
        setDecisionsByAgent(byAgent);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const handler = () => refreshAll();
    window.addEventListener("scenario-completed", handler);
    window.addEventListener("execution-completed", handler);
    const id = setInterval(refreshAll, 15000);
    return () => {
      window.removeEventListener("scenario-completed", handler);
      window.removeEventListener("execution-completed", handler);
      clearInterval(id);
    };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="animate-pulse text-muted-foreground text-[15px]">Loading...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-5 text-destructive shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
        <p className="font-semibold">API Error</p>
        <p className="text-[15px] mt-1">{error}</p>
        <p className="text-[13px] mt-2">Backend should run on port 8000: uvicorn backend.main:app --reload --port 8000</p>
      </div>
    );
  }

  return (
    <div className="space-y-8" style={{ gap: "var(--spacing-section, 32px)" }}>
      <h1 className="text-page-title">Dashboard</h1>

      {/* KPI Strip */}
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-5">
        <KPICard
          label="Active Incidents"
          value={stats?.incidents.open ?? 0}
          icon={AlertTriangle}
        />
        <KPICard
          label="Total Incidents"
          value={stats?.incidents.total ?? 0}
          icon={BarChart2}
          tooltip="Total incidents in database (including resolved)"
        />
        <KPICard
          label="Decisions"
          value={stats?.agents.total_decisions ?? 0}
          icon={ClipboardList}
          tooltip="Total agent decisions across all incidents"
        />
        <KPICard
          label="Safety"
          value={`${stats?.safety_score ?? 0}%`}
          icon={Shield}
        />
        <KPICard
          label="Eval"
          value={typeof stats?.eval_score === "number" ? (stats.eval_score * 100).toFixed(0) + "%" : "—"}
          icon={TrendingUp}
        />
      </div>

      {/* 60/40 Split */}
      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]" style={{ gap: "var(--spacing-grid, 24px)" }}>
        {/* Left 60% - Active Incidents Summary */}
        <div>
          <h2 className="text-section-title mb-4">Active Incidents</h2>
          <Card className="shadow-[0_1px_2px_rgba(0,0,0,0.05)] border-[#E5E7EB]">
            <CardContent className="p-5">
              {incidents.length === 0 ? (
                <div className="text-muted-foreground text-[15px] space-y-1">
                  <p>No active incidents</p>
                  {(stats?.incidents.total ?? 0) > 0 && (
                    <p className="text-[13px]">
                      {stats.incidents.total} resolved in database —{" "}
                      <Link href="/incidents" className="text-primary hover:underline">View all</Link>
                      {" "}or run a scenario to create new ones.
                    </p>
                  )}
                </div>
              ) : (
                <div className="space-y-4">
                  {incidents.slice(0, 5).map((inc) => (
                    <Link
                      key={inc.id}
                      href={`/incidents/${inc.id}`}
                      className="flex items-center justify-between gap-4 py-2 border-b border-[#E5E7EB] last:border-0 hover:bg-accent/30 -mx-2 px-2 rounded transition-colors"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="font-medium truncate text-[15px]">{inc.title}</p>
                        <p className="text-[13px] text-muted-foreground">
                          {(inc.metadata as { service?: string })?.service ?? "—"} • {inc.severity}
                        </p>
                      </div>
                      <Badge
                        variant={inc.severity === "critical" ? "destructive" : "secondary"}
                        className="shrink-0 text-[13px]"
                      >
                        {inc.status}
                      </Badge>
                    </Link>
                  ))}
                  {incidents.length > 5 && (
                    <Link
                      href="/incidents"
                      className="block text-center text-[14px] font-medium text-primary pt-2 hover:underline"
                    >
                      View all {incidents.length} incidents →
                    </Link>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right 40% - Service Health */}
        <div>
          <h2 className="text-section-title mb-4">Service Health</h2>
          <Card className="shadow-[0_1px_2px_rgba(0,0,0,0.05)] border-[#E5E7EB]">
            <CardContent className="p-5">
              {services?.services && services.services.length > 0 ? (
                <div className="space-y-4">
                  {services.services.map((svc) => (
                    <div key={svc.name} className="space-y-2">
                      <div className="flex justify-between items-center text-[15px]">
                        <span className="font-medium">{svc.name}</span>
                        <Badge
                          variant={
                            svc.status === "critical"
                              ? "destructive"
                              : svc.status === "warning"
                                ? "default"
                                : "secondary"
                          }
                          className="text-[13px]"
                        >
                          {svc.status}
                        </Badge>
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        <div>
                          <p className="text-[13px] text-muted-foreground">CPU</p>
                          <Progress value={Math.min(svc.cpu_percent, 100)} className="h-2" />
                        </div>
                        <div>
                          <p className="text-[13px] text-muted-foreground">Memory</p>
                          <Progress value={Math.min(svc.memory_percent, 100)} className="h-2" />
                        </div>
                        <div>
                          <p className="text-[13px] text-muted-foreground">Err rate</p>
                          <p className="text-[13px]">{(svc.error_rate * 100).toFixed(2)}%</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground text-[15px]">No service data</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Agent Status - Compact Grid */}
      <div>
        <h2 className="text-section-title mb-4">Agent Status</h2>
        <div className="grid gap-3 grid-cols-2 md:grid-cols-4">
          {AGENTS.map((a) => {
            const last = decisionsByAgent[a.id];
            const phase = result?.phases;
            let status: "idle" | "working" | "completed" = "idle";
            if (isRunning) {
              if (a.id === "watcher") status = "working";
              else if (a.id === "diagnostician") status = "working";
              else if (a.id === "strategist") status = "working";
            } else if (result && !result.error) {
              if (a.id === "watcher" && phase?.watcher) status = "completed";
              else if (a.id === "diagnostician" && phase?.diagnostician) status = "completed";
              else if (a.id === "strategist" && phase?.strategist) status = "completed";
              else if (last) status = "completed";
            } else if (last) {
              status = "completed";
            }
            const statusText = status === "working" ? "Working..." : status === "completed" ? "Completed ✓" : "Idle";
            const dotColor = status === "working" ? "bg-emerald-500 animate-pulse" : status === "completed" ? "bg-emerald-500" : "bg-muted-foreground/50";
            const lastAction = last ? parseLastAction(last.reasoning) : statusText;
            return (
              <Card
                key={a.id}
                className="shadow-[0_1px_2px_rgba(0,0,0,0.05)] border-[#E5E7EB] hover:shadow-md transition-shadow cursor-pointer"
                onClick={() => openAgentTerminal(a.id, a.name)}
              >
                <CardContent className="flex items-center gap-3 p-4">
                  <a.icon className={`h-5 w-5 shrink-0 ${a.color}`} />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-[15px] truncate">{a.name}</p>
                    <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />
                      <span className="truncate">{status === "working" ? statusText : lastAction}</span>
                    </p>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}
