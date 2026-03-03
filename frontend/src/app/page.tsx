"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  api,
  type DashboardStats,
  type ServiceHealthResponse,
  type ServiceHealth,
  type Incident,
  type WatcherStatus,
  type AgentDecision,
  type ApprovalRequest,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  AlertTriangle,
  Activity,
  Brain,
  Swords,
  Zap,
  ShieldCheck,
  TrendingUp,
  TrendingDown,
  Minus,
  Check,
  X,
  StopCircle,
  Loader2,
  ServerCrash,
  Cpu,
  MemoryStick,
  Gauge,
} from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";
import { useInjectFault } from "@/contexts/inject-fault-context";
import { LiveTerminal } from "@/components/live-terminal";
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

const SERVICES = ["user-service", "payment-service", "api-gateway"] as const;
const MAX_HISTORY = 60;

const SERVICE_COLORS: Record<string, string> = {
  "user-service": "#3b82f6",
  "payment-service": "#f59e0b",
  "api-gateway": "#10b981",
};

const THRESHOLDS: Record<string, number> = {
  cpu: 80,
  memory: 85,
  latency: 500,
  errorRate: 0.1,
};

const AGENT_META: Record<string, { label: string; color: string; icon: React.ElementType }> = {
  watcher: { label: "Watcher", color: "#3b82f6", icon: Activity },
  diagnostician: { label: "Diagnostician", color: "#eab308", icon: Brain },
  strategist: { label: "Strategist", color: "#f97316", icon: Swords },
  executor: { label: "Executor", color: "#ef4444", icon: Zap },
};

type ChartPoint = Record<string, number>;

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "--";
  const sec = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s ago`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m ago`;
}

function formatCountdown(remaining: number): string {
  if (remaining <= 0) return "expired";
  const m = Math.floor(remaining / 60);
  const s = remaining % 60;
  return m > 0 ? `${m}:${String(s).padStart(2, "0")}` : `${s}s`;
}

function statusColor(s: string | undefined): string {
  switch (s) {
    case "healthy": return "text-emerald-400";
    case "warning": return "text-yellow-400";
    case "critical": return "text-red-400";
    case "down": return "text-slate-500";
    default: return "text-slate-500";
  }
}

function statusBg(s: string | undefined): string {
  switch (s) {
    case "healthy": return "bg-emerald-500";
    case "warning": return "bg-yellow-500";
    case "critical": return "bg-red-500";
    case "down": return "bg-slate-600";
    default: return "bg-slate-600";
  }
}



function metricBarColor(value: number, threshold: number): string {
  const ratio = value / threshold;
  if (ratio < 0.6) return "#22c55e";
  if (ratio < 1.0) return "#eab308";
  return "#ef4444";
}

function deriveServiceAlertCount(svc: ServiceHealth): number {
  let count = 0;
  if (svc.cpu_percent > THRESHOLDS.cpu) count++;
  if (svc.memory_percent > THRESHOLDS.memory) count++;
  if (svc.response_time_ms > THRESHOLDS.latency) count++;
  if (svc.error_rate > THRESHOLDS.errorRate) count++;
  return count;
}

function StatusDot({ status }: { status: string | undefined }) {
  const bg = statusBg(status);
  const isActive = status === "healthy" || status === "warning" || status === "critical";
  return (
    <span className="relative flex h-2 w-2 shrink-0">
      {isActive && (
        <span className={cn("absolute inset-0 rounded-full opacity-40 animate-status-pulse", bg)} />
      )}
      <span className={cn("relative inline-flex rounded-full h-2 w-2", bg)} />
    </span>
  );
}

function WatcherRadar({ active }: { active: boolean }) {
  if (!active) {
    return (
      <div className="relative w-8 h-8 shrink-0 flex items-center justify-center opacity-40">
        <div className="absolute inset-0 rounded-full border border-slate-800" />
        <div className="w-1.5 h-1.5 rounded-full bg-slate-700" />
      </div>
    );
  }

  return (
    <div className="relative w-8 h-8 shrink-0 flex items-center justify-center">
      {/* Outer Ring */}
      <div className="absolute inset-0 rounded-full border border-emerald-500/20 shadow-[0_0_15px_rgba(16,185,129,0.1)]" />

      {/* Scanning Fan */}
      <div className="absolute inset-0 animate-radar-fan opacity-50">
        <div
          className="absolute top-0 left-1/2 w-1/2 h-1/2 bg-gradient-to-tr from-emerald-500/30 to-transparent origin-bottom-left -rotate-[45deg]"
          style={{ clipPath: 'polygon(0 0, 100% 0, 100% 100%)', borderRadius: '0 100% 0 0' }}
        />
      </div>

      {/* Subtle Pulse Ring */}
      <div className="absolute inset-0 animate-radar-ping rounded-full border border-emerald-500/30" />

      {/* Core Dot */}
      <div className="relative w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_12px_rgba(16,185,129,0.8)] animate-radar-core" />
    </div>
  );
}

function Sparkline({ data, color, height = 28 }: { data: number[]; color: string; height?: number }) {
  if (data.length < 2) return <div className="w-[80px]" style={{ height }} />;
  const chartData = data.slice(-20).map((v, i) => ({ i, v }));
  return (
    <ResponsiveContainer width={80} height={height}>
      <AreaChart data={chartData} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={`spark-${color.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.25} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone" dataKey="v" stroke={color}
          fill={`url(#spark-${color.replace("#", "")})`}
          strokeWidth={1.5} dot={false} isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function MetricBar({ value, threshold, maxScale }: { value: number; threshold: number; maxScale: number }) {
  const pct = Math.min((value / maxScale) * 100, 100);
  const thresholdPct = Math.min((threshold / maxScale) * 100, 100);
  const color = metricBarColor(value, threshold);
  return (
    <div className="relative w-full h-1.5 rounded-full bg-slate-900/50 overflow-visible border border-white/[0.02]">
      <div className="absolute h-full rounded-full progress-smooth shadow-[0_0_8px_rgba(255,255,255,0.05)]" style={{ width: `${pct}%`, backgroundColor: color }} />
      <div className="absolute h-3 w-[2px] bg-red-500/40 -top-[3px] shadow-[0_0_4px_rgba(239,68,68,0.5)]" style={{ left: `${thresholdPct}%` }} />
    </div>
  );
}

function PipelineStepper({ decisions }: { decisions: AgentDecision[] }) {
  const steps = ["detect", "diagnose", "plan", "execute"];
  const stepLabels = ["Detect", "Diagnose", "Plan", "Execute"];
  const stepColors = ["#3b82f6", "#eab308", "#f97316", "#ef4444"];
  const completedSteps = new Set((decisions ?? []).map((d) => d.decision_type));
  const lastIdx = steps.reduce((max, s, i) => (completedSteps.has(s) ? i : max), -1);

  return (
    <div className="flex items-center gap-0.5">
      {steps.map((step, i) => {
        const done = completedSteps.has(step);
        const current = i === lastIdx + 1 && lastIdx < steps.length - 1;
        return (
          <div key={step} className="flex items-center gap-0.5">
            <Tooltip>
              <TooltipTrigger asChild>
                <div
                  className={cn(
                    "w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold transition-smooth",
                    done ? "text-white scale-100" : current ? "text-white animate-status-pulse ring-1 ring-offset-1 ring-offset-[#0a0f1e]" : "bg-slate-800 text-slate-600"
                  )}
                  style={done || current ? { backgroundColor: stepColors[i] } : undefined}
                >
                  {done ? <Check className="h-2.5 w-2.5" /> : i + 1}
                </div>
              </TooltipTrigger>
              <TooltipContent className="text-[10px]">{stepLabels[i]}</TooltipContent>
            </Tooltip>
            {i < 3 && <div className={cn("h-px w-2 transition-smooth", done ? "bg-emerald-500/60" : "bg-slate-800")} />}
          </div>
        );
      })}
    </div>
  );
}

export default function DashboardPage() {
  const { open: openInjectFault } = useInjectFault();

  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [prevStats, setPrevStats] = useState<DashboardStats | null>(null);
  const [services, setServices] = useState<ServiceHealthResponse | null>(null);
  const [watcherStatus, setWatcherStatus] = useState<WatcherStatus | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [decisions, setDecisions] = useState<AgentDecision[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [cpuHistory, setCpuHistory] = useState<ChartPoint[]>([]);
  const [memHistory, setMemHistory] = useState<ChartPoint[]>([]);
  const [latencyHistory, setLatencyHistory] = useState<ChartPoint[]>([]);
  const [activeTab, setActiveTab] = useState("cpu");

  const [activeFault, setActiveFault] = useState<{ target: string; fault: string; duration: number; startedAt: number } | null>(null);
  const [faultRemaining, setFaultRemaining] = useState(0);
  const [stoppingChaos, setStoppingChaos] = useState(false);
  const [processingApproval, setProcessingApproval] = useState<string | null>(null);

  useEffect(() => {
    if (!activeFault || activeFault.duration <= 0) return;
    const tick = () => {
      const elapsed = Math.floor((Date.now() - activeFault.startedAt) / 1000);
      const rem = Math.max(0, activeFault.duration - elapsed);
      setFaultRemaining(rem);
      if (rem <= 0) setActiveFault(null);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [activeFault]);

  const pushHistory = useCallback((svcList: ServiceHealth[]) => {
    const now = Date.now();
    const mkPoint = (extract: (s: ServiceHealth) => number): ChartPoint => {
      const p: ChartPoint = { time: now };
      for (const s of svcList) p[s.name] = extract(s);
      return p;
    };
    const trim = (arr: ChartPoint[]): ChartPoint[] => arr.length >= MAX_HISTORY ? arr.slice(arr.length - MAX_HISTORY + 1) : arr;

    setCpuHistory((h) => trim([...h, mkPoint((s) => s.cpu_percent)]));
    setMemHistory((h) => trim([...h, mkPoint((s) => s.memory_percent)]));
    setLatencyHistory((h) => trim([...h, mkPoint((s) => s.response_time_ms)]));
  }, []);

  useEffect(() => {
    Promise.all([
      api.getStats().catch(() => null),
      api.getServiceHealth().catch(() => null),
      api.getIncidents("open").catch(() => null),
      api.getAgentDecisions(undefined, 20).catch(() => null),
      api.getWatcherStatus().catch(() => null),
      api.getApprovals().catch(() => null),
    ])
      .then(([s, h, inc, dec, w, app]) => {
        if (s) setStats(s);
        if (h) { setServices(h); if (h.services?.length > 0) pushHistory(h.services); }
        setIncidents(inc?.incidents ?? []);
        setDecisions(dec?.decisions ?? []);
        if (w) setWatcherStatus(w);
        setApprovals(app?.approvals ?? []);
      })
      .catch((e) => setError(e?.message ?? "Cannot reach backend"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      api.getServiceHealth().then((h) => {
        if (h) { setServices(h); if (h.services?.length > 0) pushHistory(h.services); }
      }).catch(() => { });
    }, 3000);
    return () => clearInterval(id);
  }, [pushHistory]);

  useEffect(() => {
    const id = setInterval(() => {
      api.getWatcherStatus().then(setWatcherStatus).catch(() => { });
      api.getIncidents("open").then((r) => setIncidents(r?.incidents ?? [])).catch(() => { });
      api.getAgentDecisions(undefined, 20).then((r) => setDecisions(r?.decisions ?? [])).catch(() => { });
    }, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      api.getApprovals().then((r) => setApprovals(r?.approvals ?? [])).catch(() => { });
    }, 3000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      api.getStats().then((s) => {
        if (s) { setPrevStats(stats); setStats(s); }
      }).catch(() => { });
    }, 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stats]);

  useEffect(() => {
    const faultHandler = (e: Event) => setActiveFault((e as CustomEvent).detail);
    const refreshHandler = () => {
      api.getServiceHealth().then(setServices).catch(() => { });
      api.getIncidents("open").then((r) => setIncidents(r?.incidents ?? [])).catch(() => { });
      api.getAgentDecisions(undefined, 20).then((r) => setDecisions(r?.decisions ?? [])).catch(() => { });
      api.getApprovals().then((r) => setApprovals(r?.approvals ?? [])).catch(() => { });
    };
    window.addEventListener("fault-injected", faultHandler);
    window.addEventListener("execution-completed", refreshHandler);
    window.addEventListener("approvals-updated", refreshHandler);
    return () => {
      window.removeEventListener("fault-injected", faultHandler);
      window.removeEventListener("execution-completed", refreshHandler);
      window.removeEventListener("approvals-updated", refreshHandler);
    };
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "i") openInjectFault();
      if (e.key === "1") setActiveTab("cpu");
      if (e.key === "2") setActiveTab("memory");
      if (e.key === "3") setActiveTab("latency");
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [openInjectFault]);

  const handleStopChaos = async () => {
    if (!activeFault) return;
    setStoppingChaos(true);
    try {
      const targets = activeFault.target.includes("+") ? activeFault.target.split("+").map((t) => t.trim()) : [activeFault.target];
      for (const t of targets) {
        if (t === "redis") continue;
        try { await api.stopChaos(t); } catch { /* ignore */ }
      }
      setActiveFault(null);
      toast.success("Chaos stopped");
    } catch (e) {
      toast.error(`Failed: ${(e as Error).message}`);
    } finally {
      setStoppingChaos(false);
    }
  };

  const handleApprove = async (req: ApprovalRequest) => {
    setProcessingApproval(req.id);
    try {
      const res = await api.approve(req.id);
      toast.success(res.incident_resolved ? "Approved — incident resolved" : "Approved — action executed");
      setApprovals((prev) => prev.filter((a) => a.id !== req.id));
      window.dispatchEvent(new CustomEvent("execution-completed", { detail: { incident_id: res.incident_id } }));
    } catch {
      toast.error("Failed to approve");
    } finally {
      setProcessingApproval(null);
    }
  };

  const handleReject = async (req: ApprovalRequest) => {
    setProcessingApproval(req.id);
    try {
      await api.reject(req.id);
      toast.success("Action rejected");
      setApprovals((prev) => prev.filter((a) => a.id !== req.id));
      window.dispatchEvent(new CustomEvent("approvals-updated"));
    } catch {
      toast.error("Failed to reject");
    } finally {
      setProcessingApproval(null);
    }
  };

  const svcList = services?.services ?? [];
  const healthyCount = svcList.filter((s) => s.status === "healthy").length;
  const totalCount = svcList.length;
  const systemHealthPct = totalCount > 0 ? Math.round((healthyCount / totalCount) * 100) : 0;

  const trendIcon = (current: number | undefined, previous: number | undefined) => {
    if (current === undefined || previous === undefined) return <Minus className="h-3 w-3 text-slate-600" />;
    if (current > previous) return <TrendingUp className="h-3 w-3 text-red-400" />;
    if (current < previous) return <TrendingDown className="h-3 w-3 text-emerald-400" />;
    return <Minus className="h-3 w-3 text-slate-600" />;
  };

  const svcSparklines = useMemo(() => {
    const result: Record<string, { cpu: number[]; memory: number[]; latency: number[] }> = {};
    for (const name of SERVICES) {
      result[name] = {
        cpu: cpuHistory.map((p) => p[name] ?? 0),
        memory: memHistory.map((p) => p[name] ?? 0),
        latency: latencyHistory.map((p) => p[name] ?? 0),
      };
    }
    return result;
  }, [cpuHistory, memHistory, latencyHistory]);

  const activeChartData = activeTab === "cpu" ? cpuHistory : activeTab === "memory" ? memHistory : latencyHistory;
  const activeThreshold = activeTab === "cpu" ? THRESHOLDS.cpu : activeTab === "memory" ? THRESHOLDS.memory : THRESHOLDS.latency;
  const activeChartLabel = activeTab === "cpu" ? "CPU %" : activeTab === "memory" ? "Memory %" : "Latency (ms)";

  const decisionsByIncident = useMemo(() => {
    const m = new Map<string, AgentDecision[]>();
    for (const d of decisions ?? []) {
      if (!d.incident_id) continue;
      const arr = m.get(d.incident_id) || [];
      arr.push(d);
      m.set(d.incident_id, arr);
    }
    return m;
  }, [decisions]);

  const serviceAlerts = useMemo(() => {
    const result: Record<string, { count: number; status: string }> = {};
    for (const svc of svcList) {
      result[svc.name] = {
        count: deriveServiceAlertCount(svc),
        status: svc.status ?? "unknown",
      };
    }
    return result;
  }, [svcList]);

  if (loading) {
    return (
      <div className="space-y-4 stagger-children">
        <div className="h-8 w-48 bg-slate-800/50 rounded-lg shimmer-loading" />
        <div className="grid grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => <div key={i} className="h-[88px] bg-slate-800/30 rounded-xl shimmer-loading" />)}
        </div>
        <div className="grid grid-cols-3 gap-3">
          {[...Array(3)].map((_, i) => <div key={i} className="h-[180px] bg-slate-800/30 rounded-xl shimmer-loading" />)}
        </div>
        <div className="h-[280px] bg-slate-800/30 rounded-xl shimmer-loading" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-[400px] animate-fade-in">
        <Card className="max-w-md border-red-500/20 bg-red-950/10">
          <CardContent className="p-6 text-center space-y-3">
            <ServerCrash className="h-10 w-10 text-red-400 mx-auto" />
            <p className="text-base font-semibold text-red-400">Cannot reach backend</p>
            <p className="text-sm text-slate-400">{error}</p>
            <p className="text-[11px] text-slate-600 font-mono">docker compose up -d && open http://localhost:8000/health</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">

      <div className="flex items-center justify-between gap-4 animate-fade-in bg-slate-900/60 border border-white/[0.05] p-3 rounded-xl shadow-2xl relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-r from-emerald-500/5 via-transparent to-transparent pointer-events-none" />
        <div className="flex items-center gap-4 relative z-10">
          <WatcherRadar active={!!watcherStatus?.enabled} />
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="text-emerald-400 font-bold uppercase tracking-[0.12em] text-[11px] leading-none whitespace-nowrap">Watcher System Online</span>
              <span className="relative flex h-1.5 w-1.5 shrink-0 translate-y-[0.5px]">
                <span className="absolute inset-0 rounded-full bg-emerald-500 opacity-40 animate-ping" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]" />
              </span>
            </div>
            <div className="text-[10px] flex items-center gap-2 text-slate-500 font-bold uppercase tracking-wider mt-0.5">
              <span>Poll Interval: {watcherStatus?.poll_interval_seconds ?? 15}s</span>
              <span className="text-slate-800">•</span>
              <span className="uppercase">SCANNING {totalCount} SERVICES</span>
              {watcherStatus?.last_check && (
                <>
                  <span className="text-slate-800">•</span>
                  <span className="tabular-nums">Last Sync: {timeAgo(watcherStatus.last_check)}</span>
                </>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1.5 pr-2">
          {svcList.map((svc) => {
            const alert = serviceAlerts[svc.name];
            const alertCount = alert?.count ?? 0;
            const svcStatus = alert?.status ?? "unknown";
            const shortName = svc.name.replace("-service", "");
            return (
              <Tooltip key={svc.name}>
                <TooltipTrigger asChild>
                  <Badge
                    variant="outline"
                    className={cn(
                      "text-[10px] font-mono tabular-nums transition-smooth h-5 px-2 gap-1.5 min-w-[85px] justify-between",
                      svcStatus === "healthy" && "border-emerald-500/20 text-emerald-400",
                      svcStatus === "warning" && "border-yellow-500/30 text-yellow-400 animate-status-pulse",
                      svcStatus === "critical" && "border-red-500/30 text-red-400 bg-red-500/5 animate-status-pulse",
                      svcStatus === "down" && "border-slate-700 text-slate-600",
                    )}
                  >
                    <StatusDot status={svcStatus} />
                    <span>{shortName}</span>
                    <span className="font-bold">{alertCount > 0 ? alertCount : "OK"}</span>
                  </Badge>
                </TooltipTrigger>
                <TooltipContent className="text-[10px]">
                  <p>{svc.name}: {svcStatus}{alertCount > 0 ? ` — ${alertCount} threshold${alertCount > 1 ? "s" : ""} breached` : ""}</p>
                </TooltipContent>
              </Tooltip>
            );
          })}
        </div>
      </div>

      {activeFault && (
        <div className="animate-slide-down rounded-xl border-2 border-red-500/50 bg-red-950/20 backdrop-blur-xl px-5 py-3 flex items-center justify-between shadow-[0_0_30px_rgba(239,68,68,0.15)] relative overflow-hidden group">
          <div className="absolute inset-0 bg-gradient-to-r from-red-500/10 via-transparent to-transparent" />
          <div className="absolute left-0 top-0 bottom-0 w-1 bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.8)]" />
          <div className="flex items-center gap-4 relative z-10">
            <div className="w-10 h-10 rounded-lg bg-red-500 flex items-center justify-center shadow-[0_0_15px_rgba(239,68,68,0.5)]">
              <Zap className="h-5 w-5 text-white animate-pulse" />
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <span className="text-red-400 font-black uppercase tracking-[0.25em] text-[13px]">CRITICAL FAULT ACTIVE</span>
                <Badge variant="outline" className="border-red-500/50 text-red-500 tabular-nums text-[11px] font-black tracking-widest bg-red-500/10 px-2 h-5">
                  {formatCountdown(faultRemaining)}
                </Badge>
              </div>
              <div className="text-[11px] font-bold uppercase tracking-wider text-red-300 opacity-80 mt-0.5">
                Target: {activeFault.target} • Vector: {activeFault.fault}
              </div>
            </div>
          </div>
          <Button size="sm" variant="outline" onClick={handleStopChaos} disabled={stoppingChaos} className="border-red-500/50 text-red-400 hover:bg-red-500 hover:text-white h-9 px-6 text-[11px] font-black uppercase tracking-widest rounded-lg transition-all duration-300 relative z-10 shadow-[0_0_15px_rgba(239,68,68,0.2)]">
            {stoppingChaos ? <Loader2 className="h-3 w-3 animate-spin" /> : <StopCircle className="h-4 w-4" />}
            Emergency Stop
          </Button>
        </div>
      )}

      {/* 3. KPI Strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 stagger-children">
        <Card className="bg-slate-900/40 backdrop-blur-md border-slate-800/50 card-interactive hover:border-slate-700/60 shadow-2xl">
          <CardContent className="p-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-1.5">Total Incidents</p>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-black tabular-nums text-white metric-value tracking-tighter">{stats?.incidents?.total ?? 0}</span>
              {trendIcon(stats?.incidents?.total, prevStats?.incidents?.total)}
            </div>
            <p className="text-[10px] text-slate-600 mt-1 uppercase tracking-wider font-bold">{stats?.agents?.total_tool_calls ?? 0} tool calls</p>
          </CardContent>
        </Card>

        <Card className={cn(
          "backdrop-blur-md border-slate-800/50 card-interactive border-smooth hover:border-slate-700/60 shadow-2xl transition-all duration-500",
          (stats?.incidents?.open ?? 0) > 0 ? "bg-red-950/20 border-red-500/30 animate-glow-red" : "bg-slate-900/40"
        )}>
          <CardContent className="p-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-1.5">Open Incidents</p>
            <div className="flex items-baseline gap-2">
              <span className={cn("text-2xl font-black tabular-nums metric-value tracking-tighter", (stats?.incidents?.open ?? 0) > 0 ? "text-red-500 drop-shadow-[0_0_8px_rgba(239,68,68,0.4)]" : "text-white")}>
                {stats?.incidents?.open ?? 0}
              </span>
              {trendIcon(stats?.incidents?.open, prevStats?.incidents?.open)}
            </div>
            <p className="text-[10px] text-slate-600 mt-1 uppercase tracking-wider font-bold">{(incidents?.length ?? 0) > 0 ? "Investigating" : "All clear"}</p>
          </CardContent>
        </Card>

        <Card className="bg-slate-900/40 backdrop-blur-md border-slate-800/50 card-interactive hover:border-slate-700/60 shadow-2xl">
          <CardContent className="p-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-1.5">Agent Decisions</p>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-black tabular-nums text-white metric-value tracking-tighter">{stats?.agents?.total_decisions ?? 0}</span>
            </div>
            <p className="text-[10px] text-slate-600 mt-1 uppercase tracking-wider font-bold">{stats?.agents?.active_agents ?? 0} active agents</p>
          </CardContent>
        </Card>

        <Card className="bg-slate-900/40 backdrop-blur-md border-slate-800/50 card-interactive hover:border-slate-700/60 shadow-2xl">
          <CardContent className="p-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500 mb-1.5">System Health</p>
            <div className="flex items-center gap-4">
              <span className={cn(
                "text-2xl font-black tabular-nums metric-value tracking-tighter",
                systemHealthPct === 100 ? "text-emerald-400 drop-shadow-[0_0_8px_rgba(34,197,94,0.3)]" : systemHealthPct >= 66 ? "text-yellow-400" : "text-red-400"
              )}>
                {systemHealthPct}%
              </span>
              <svg className="w-10 h-10 -rotate-90 drop-shadow-[0_0_5px_rgba(0,0,0,0.2)]" viewBox="0 0 36 36">
                <circle cx="18" cy="18" r="14" stroke="#0f172a" strokeWidth="4" fill="none" />
                <circle
                  cx="18" cy="18" r="14"
                  stroke={systemHealthPct === 100 ? "#22c55e" : systemHealthPct >= 66 ? "#eab308" : "#ef4444"}
                  strokeWidth="4" fill="none"
                  strokeDasharray={`${systemHealthPct * 0.88} 88`}
                  className="transition-smooth"
                  strokeLinecap="round"
                />
              </svg>
            </div>
            <p className="text-[10px] text-slate-600 mt-1 uppercase tracking-wider font-bold">{healthyCount}/{totalCount} services up</p>
          </CardContent>
        </Card>
      </div>

      {/* 4. Service Health Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {svcList.map((svc) => {
          const sparkData = svcSparklines[svc.name];
          const isDown = svc.status === "down" || svc.status === "unknown";
          const metrics = [
            { icon: Cpu, label: "CPU", value: svc.cpu_percent, fmt: `${svc.cpu_percent.toFixed(1)}%`, threshold: THRESHOLDS.cpu, max: 120, spark: sparkData?.cpu },
            { icon: MemoryStick, label: "Mem", value: svc.memory_percent, fmt: `${svc.memory_percent.toFixed(1)}%`, threshold: THRESHOLDS.memory, max: 120, spark: sparkData?.memory },
            { icon: Gauge, label: "Lat", value: svc.response_time_ms, fmt: `${svc.response_time_ms.toFixed(0)}ms`, threshold: THRESHOLDS.latency, max: 1500, spark: sparkData?.latency },
          ];

          return (
            <Card
              key={svc.name}
              className={cn(
                "card-interactive border border-slate-800/50 bg-slate-900/40 backdrop-blur-md shadow-2xl transition-all duration-500 overflow-hidden relative",
                svc.status === "critical" && "border-red-500/30 bg-red-950/10 animate-glow-red",
                svc.status === "warning" && "border-yellow-500/20 bg-yellow-950/5",
                isDown && "opacity-60 grayscale border-slate-700/30"
              )}
            >
              {svc.status === "critical" && <div className="absolute top-0 left-0 right-0 h-0.5 bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.8)]" />}
              <CardContent className="p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex flex-col">
                    <div className="flex items-center gap-2">
                      <StatusDot status={svc.status} />
                      <span className="font-black text-[12px] uppercase tracking-[0.15em] text-white">{svc.name}</span>
                    </div>
                  </div>
                  <Badge className={cn(
                    "text-[9px] font-black uppercase h-5 px-2 tracking-widest border-none shadow-lg",
                    svc.status === "healthy" ? "bg-emerald-600 text-white" :
                      svc.status === "warning" ? "bg-yellow-500 text-slate-950 shadow-[0_0_10px_rgba(234,179,8,0.3)]" :
                        svc.status === "critical" ? "bg-red-600 text-white shadow-[0_0_15px_rgba(239,68,68,0.4)]" : "bg-slate-700 text-slate-400"
                  )}>
                    {svc.status}
                  </Badge>
                </div>

                {isDown ? (
                  <div className="py-3 text-center text-slate-600 text-xs">Service unreachable</div>
                ) : (
                  <div className="space-y-2">
                    {metrics.map((m) => (
                      <div key={m.label} className="flex items-center gap-2">
                        <m.icon className="h-3 w-3 text-slate-600 shrink-0" />
                        <span className="text-[10px] text-slate-500 w-8 shrink-0">{m.label}</span>
                        <span className={cn(
                          "text-[11px] font-mono tabular-nums w-12 text-right shrink-0 metric-value",
                          m.value > m.threshold ? "text-red-400" : "text-slate-300"
                        )}>
                          {m.fmt}
                        </span>
                        <div className="flex-1 min-w-0">
                          <MetricBar value={m.value} threshold={m.threshold} maxScale={m.max} />
                        </div>
                        {m.spark && <Sparkline data={m.spark} color={metricBarColor(m.value, m.threshold)} />}
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* 5. Real-Time Metrics Chart */}
      <Card className="bg-slate-900/40 backdrop-blur-md border-slate-800/50 shadow-2xl">
        <CardContent className="p-4">
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <div className="flex items-center justify-between mb-4">
              <div className="flex flex-col">
                <h2 className="text-[12px] font-bold uppercase tracking-[0.2em] text-slate-400">Tactical Telemetry</h2>
                <p className="text-[10px] text-slate-600 font-bold uppercase tracking-wider mt-0.5">Real-time system health data</p>
              </div>
              <TabsList className="bg-slate-950/50 h-8 gap-1 p-1 border border-white/[0.03]">
                <TabsTrigger value="cpu" className="text-[10px] h-6 px-4 font-black uppercase tracking-widest data-[state=active]:bg-blue-600 data-[state=active]:text-white">CPU</TabsTrigger>
                <TabsTrigger value="memory" className="text-[10px] h-6 px-4 font-black uppercase tracking-widest data-[state=active]:bg-yellow-500 data-[state=active]:text-slate-950">MEM</TabsTrigger>
                <TabsTrigger value="latency" className="text-[10px] h-6 px-4 font-black uppercase tracking-widest data-[state=active]:bg-orange-500 data-[state=active]:text-white">LAT</TabsTrigger>
              </TabsList>
            </div>
            <TabsContent value={activeTab} className="mt-0" forceMount>
              <div style={{ height: 240 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={activeChartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                    <XAxis dataKey="time" tick={false} axisLine={{ stroke: "#1e293b" }} tickLine={false} />
                    <YAxis tick={{ fill: "#475569", fontSize: 10 }} axisLine={{ stroke: "#1e293b" }} tickLine={false} domain={[0, "auto"]} width={36} />
                    <RechartsTooltip
                      contentStyle={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px", fontSize: "11px", color: "#e2e8f0", boxShadow: "0 8px 30px rgba(0,0,0,0.4)" }}
                      labelFormatter={() => activeChartLabel}
                      formatter={(value: number | string | undefined) => {
                        const v = typeof value === "number" ? value : 0;
                        return activeTab === "latency" ? `${v.toFixed(0)}ms` : `${v.toFixed(2)}%`;
                      }}
                    />
                    <Legend wrapperStyle={{ fontSize: "10px", color: "#64748b" }} iconType="circle" iconSize={5} />
                    <ReferenceLine y={activeThreshold} stroke="#ef4444" strokeDasharray="6 3" strokeOpacity={0.3} />
                    {SERVICES.map((name) => (
                      <Line key={name} type="monotone" dataKey={name} stroke={SERVICE_COLORS[name]} strokeWidth={1.5} dot={false} isAnimationActive={false} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      {/* 6. Two Columns: Incidents + Terminal */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Card className="bg-slate-900/40 backdrop-blur-md border-slate-800/50 shadow-2xl h-[420px] flex flex-col overflow-hidden">
          <CardContent className="p-4 flex flex-col flex-1 min-h-0">
            <div className="flex items-center justify-between mb-4 shrink-0">
              <div className="flex flex-col">
                <h2 className="text-[12px] font-bold uppercase tracking-[0.2em] text-slate-400">Active Incidents</h2>
                <div className="h-0.5 w-8 bg-red-500/40 mt-1 rounded-full" />
              </div>
              <Link href="/incidents" className="text-[10px] font-black uppercase tracking-widest text-blue-400 hover:text-blue-300 transition-smooth flex items-center gap-1">
                Full Log <span className="text-[12px]">&rarr;</span>
              </Link>
            </div>
            {(!incidents || incidents.length === 0) ? (
              <div className="py-8 text-center animate-fade-in flex-1 flex flex-col items-center justify-center">
                <div className="w-12 h-12 rounded-full bg-emerald-500/5 flex items-center justify-center mb-3">
                  <ShieldCheck className="h-6 w-6 text-emerald-500/40" />
                </div>
                <p className="text-[11px] font-black uppercase tracking-[0.2em] text-emerald-400/70">All systems green</p>
                <p className="text-[10px] text-slate-600 mt-1 font-bold uppercase tracking-wider">Passive surveillance active</p>
              </div>
            ) : (
              <ScrollArea className="flex-1 min-h-0 pr-2">
                <div className="space-y-2">
                  {incidents.map((inc) => {
                    if (!inc) return null;
                    const service = (inc.metadata as { service?: string })?.service ?? "unknown";
                    const incDecisions = decisionsByIncident.get(inc.id) || [];
                    return (
                      <Link key={inc.id} href={`/incidents/${inc.id}`}>
                        <div className={cn(
                          "p-3 rounded-lg border transition-all duration-300 hover:bg-white/[0.04] cursor-pointer animate-slide-up group/item",
                          inc.severity === "critical" ? "border-red-500/30 bg-red-950/10" : "border-slate-800/50 bg-slate-800/20"
                        )}>
                          <div className="flex items-start justify-between gap-3 mb-2">
                            <div className="flex items-center gap-2 min-w-0">
                              <Badge className={cn("text-[8px] font-black uppercase tracking-widest h-4 px-1.5 border-none",
                                inc.severity === 'critical' ? 'bg-red-600 text-white' :
                                  inc.severity === 'high' ? 'bg-orange-500 text-white' :
                                    inc.severity === 'medium' ? 'bg-yellow-500 text-slate-950' : 'bg-emerald-600 text-white'
                              )}>
                                {inc.severity}
                              </Badge>
                              <span className="text-[10px] text-slate-400 font-black uppercase tracking-wider truncate">{service}</span>
                            </div>
                            <span className="text-[9px] text-slate-600 font-bold uppercase tracking-widest tabular-nums shrink-0">{timeAgo(inc.detected_at)}</span>
                          </div>
                          <p className="text-[12px] font-bold text-slate-200 group-hover/item:text-white transition-colors truncate mb-2">{inc.title ?? "Untitled"}</p>
                          <div className="flex items-center justify-between opacity-80 group-hover/item:opacity-100 transition-opacity">
                            <PipelineStepper decisions={incDecisions} />
                            {inc.root_cause && <span className="text-[9px] font-black uppercase tracking-widest text-slate-500 truncate max-w-[120px]">{inc.root_cause}</span>}
                          </div>
                        </div>
                      </Link>
                    );
                  })}
                </div>
              </ScrollArea>
            )}
          </CardContent>
        </Card>

        {/* Mac Terminal Live Log Panel */}
        <div className="h-[400px]">
          <LiveTerminal />
        </div>
      </div>

      {/* 7. Pending Approvals */}
      {(approvals?.length ?? 0) > 0 && (
        <div className="space-y-3 animate-slide-up bg-slate-900/40 backdrop-blur-md border border-yellow-500/20 p-4 rounded-xl shadow-2xl">
          <div className="flex items-center gap-3">
            <div className="flex flex-col">
              <h2 className="text-[12px] font-black uppercase tracking-[0.25em] text-yellow-400">Manual Authorization Required</h2>
              <div className="h-0.5 w-12 bg-yellow-500/40 mt-1 rounded-full" />
            </div>
            <Badge className="bg-yellow-500 text-slate-950 text-[10px] font-black h-5 px-2 rounded-md shadow-[0_0_10px_rgba(234,179,8,0.4)]">
              {approvals.length} PENDING
            </Badge>
          </div>
          <div className="space-y-3">
            {approvals.map((req) => {
              if (!req) return null;
              const pendingMs = Date.now() - new Date(req.requested_at).getTime();
              const pendingMin = pendingMs / 60000;
              const incDecisions = req.incident_id ? decisionsByIncident.get(req.incident_id) || [] : [];
              const watcherD = incDecisions.find((d) => d.agent_name === "watcher");
              const diagD = incDecisions.find((d) => d.agent_name === "diagnostician");
              const stratD = incDecisions.find((d) => d.agent_name === "strategist");

              const parseR = (d: AgentDecision | undefined) => {
                if (!d?.reasoning) return null;
                try { const p = JSON.parse(d.reasoning); return typeof p === "object" && p !== null ? p as Record<string, unknown> : null; } catch { return null; }
              };
              const watcherR = parseR(watcherD);
              const diagR = parseR(diagD);
              const stratR = parseR(stratD);
              const currentService = svcList.find((s) => s.name === req.service);

              return (
                <Card
                  key={req.id}
                  className={cn(
                    "border-2 transition-all duration-500 overflow-hidden relative",
                    pendingMin > 5 ? "border-red-500/50 bg-red-950/20 animate-glow-red" :
                      pendingMin > 2 ? "border-orange-500/40 bg-orange-950/10" : "border-yellow-500/30 bg-yellow-950/10"
                  )}
                >
                  <div className={cn("absolute top-0 left-0 bottom-0 w-1",
                    pendingMin > 5 ? "bg-red-500" : pendingMin > 2 ? "bg-orange-500" : "bg-yellow-500"
                  )} />
                  <CardContent className="p-4 space-y-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2.5">
                        <AlertTriangle className={cn("h-4 w-4", pendingMin > 5 ? "text-red-400" : "text-yellow-400")} />
                        <span className="text-[11px] font-black uppercase tracking-[0.2em] text-white">Action Authorization</span>
                      </div>
                      <span className="text-[10px] text-slate-500 font-black uppercase tracking-widest tabular-nums">Received {timeAgo(req.requested_at)}</span>
                    </div>

                    <div className="flex items-center gap-3 bg-white/[0.03] p-2 rounded-lg border border-white/[0.05]">
                      <Badge variant="outline" className="text-[10px] font-black tracking-tighter h-5 px-2 bg-slate-950/50 border-slate-700">{req.tool}</Badge>
                      <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Target: <span className="text-slate-200">{req.service}</span></span>
                      <Badge className={cn("text-[9px] font-black ml-auto h-5 px-2 tracking-widest border-none shadow-md",
                        req.risk_level === "risky" ? "bg-red-600 text-white shadow-[0_0_10px_rgba(220,38,38,0.3)]" : "bg-emerald-600 text-white")}>
                        {req.risk_level}
                      </Badge>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {!!watcherR && (
                        <div className="p-3 rounded-lg bg-slate-950/60 border border-white/[0.05]">
                          <p className="text-[9px] font-black uppercase tracking-[0.2em] text-slate-500 mb-1">Observation</p>
                          <p className="text-[11px] font-medium text-slate-300">{(watcherR.summary as string) || "Anomaly detected"}</p>
                        </div>
                      )}
                      {!!diagR && (
                        <div className="p-3 rounded-lg bg-slate-950/60 border border-white/[0.05]">
                          <p className="text-[9px] font-black uppercase tracking-[0.2em] text-slate-500 mb-1">Diagnostic Result</p>
                          <p className="text-[11px] font-medium text-slate-300">
                            {(diagR.root_cause_category as string) || (diagR.root_cause as string) || "Unknown"}
                            {typeof diagR.confidence === "number" && <span className="text-slate-500 ml-1.5 font-bold">({(diagR.confidence * 100).toFixed(0)}%)</span>}
                          </p>
                        </div>
                      )}
                    </div>

                    {currentService && (
                      <div className="flex items-center gap-4 text-[10px] font-black uppercase tracking-[0.15em] text-slate-500 pb-1">
                        <span>CPU <span className={cn("font-black tabular-nums ml-1", currentService.cpu_percent > 80 ? "text-red-400" : "text-emerald-400")}>{currentService.cpu_percent.toFixed(1)}%</span></span>
                        <span>MEM <span className={cn("font-black tabular-nums ml-1", currentService.memory_percent > 85 ? "text-red-400" : "text-emerald-400")}>{currentService.memory_percent.toFixed(1)}%</span></span>
                        <span>LAT <span className={cn("font-black tabular-nums ml-1", currentService.response_time_ms > 500 ? "text-red-400" : "text-emerald-400")}>{currentService.response_time_ms.toFixed(0)}MS</span></span>
                      </div>
                    )}

                    <div className="flex items-center gap-2 pt-1 border-t border-white/[0.05]">
                      <Button size="sm" variant="ghost" onClick={() => handleReject(req)} disabled={processingApproval === req.id} className="text-red-400 hover:bg-red-500/10 h-8 text-[11px] font-black uppercase tracking-widest px-4 border border-transparent hover:border-red-500/30">
                        <X className="h-3.5 w-3.5 mr-1.5" /> Abort Action
                      </Button>
                      <Button size="sm" onClick={() => handleApprove(req)} disabled={processingApproval === req.id} className="bg-emerald-600 hover:bg-emerald-500 text-white h-8 text-[11px] font-black uppercase tracking-widest px-5 shadow-[0_4px_15px_rgba(5,150,105,0.3)] ml-auto">
                        {processingApproval === req.id ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : <Check className="h-3.5 w-3.5 mr-1.5" />}
                        Authorize Execution
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
