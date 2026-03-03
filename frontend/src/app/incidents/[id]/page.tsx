"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  api,
  type AgentTraceResponse,
  type IncidentEventsResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  ArrowLeft, Activity, Brain, Swords, Zap, Check, ChevronDown, ChevronRight, Clock, ServerCrash, Table,
} from "lucide-react";

const AGENT_META: Record<string, { label: string; color: string; icon: React.ElementType; bgColor: string; borderColor: string; shadowColor: string }> = {
  watcher: {
    label: "Watcher",
    color: "#3b82f6",
    icon: Activity,
    bgColor: "bg-blue-600",
    borderColor: "border-blue-400/50",
    shadowColor: "shadow-blue-500/20"
  },
  diagnostician: {
    label: "Diagnostician",
    color: "#eab308",
    icon: Brain,
    bgColor: "bg-yellow-500",
    borderColor: "border-yellow-400/50",
    shadowColor: "shadow-yellow-500/20"
  },
  strategist: {
    label: "Strategist",
    color: "#f97316",
    icon: Swords,
    bgColor: "bg-orange-500",
    borderColor: "border-orange-400/50",
    shadowColor: "shadow-orange-500/20"
  },
  executor: {
    label: "Executor",
    color: "#ef4444",
    icon: Zap,
    bgColor: "bg-red-600",
    borderColor: "border-red-400/50",
    shadowColor: "shadow-red-500/20"
  },
};

function timeStr(iso: string | null): string {
  if (!iso) return "--:--:--";
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDuration(from: string | null, to: string | null): string {
  if (!from) return "--";
  const start = new Date(from).getTime();
  const end = to ? new Date(to).getTime() : Date.now();
  const sec = Math.max(0, Math.floor((end - start) / 1000));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
}

function statusBadgeStyles(s: string | null | undefined): string {
  switch (s) {
    case "open": return "bg-red-500/10 text-red-400 border-red-500/20 ring-1 ring-red-500/30 animate-pulse-subtle";
    case "investigating": return "bg-yellow-500/10 text-yellow-400 border-yellow-500/20 ring-1 ring-yellow-500/30";
    case "resolved": return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 ring-1 ring-emerald-500/30";
    default: return "bg-slate-500/10 text-slate-400 border-slate-500/20";
  }
}

function parseReasoning(raw: string | null | undefined): Record<string, unknown> {
  if (!raw) return {};
  try {
    const p = JSON.parse(raw);
    if (typeof p === "object" && p !== null) return p as Record<string, unknown>;
  } catch { /* ignore */ }
  return { raw };
}

function ExpandableSection({ title, children, defaultOpen = false }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-slate-800/50 rounded-lg overflow-hidden">
      <button
        type="button"
        className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-[11px] font-medium text-slate-500 hover:bg-white/[0.02] transition-smooth"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown className="h-2.5 w-2.5" /> : <ChevronRight className="h-2.5 w-2.5" />}
        {title}
      </button>
      {open && <div className="px-3 py-2 border-t border-slate-800/30 bg-slate-900/20 text-[11px] font-mono text-slate-500">{children}</div>}
    </div>
  );
}

export default function IncidentDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [data, setData] = useState<AgentTraceResponse | null>(null);
  const [events, setEvents] = useState<IncidentEventsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(() => {
    Promise.all([
      api.getAgentTrace(id).catch(() => null),
      api.getIncidentEvents(id).catch(() => null),
    ])
      .then(([trace, evts]) => {
        if (trace) setData(trace);
        else if (!data) setError("Incident not found");
        if (evts) setEvents(evts);
      })
      .catch((e) => setError(e?.message ?? "Failed to load incident"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => { const intv = setInterval(fetchData, 3000); return () => clearInterval(intv); }, [fetchData]);
  useEffect(() => {
    const handler = () => fetchData();
    window.addEventListener("execution-completed", handler);
    return () => window.removeEventListener("execution-completed", handler);
  }, [fetchData]);

  if (loading) {
    return (
      <div className="space-y-3 stagger-children">
        <div className="h-7 w-36 bg-slate-800/30 rounded-lg shimmer-loading" />
        <div className="h-[120px] bg-slate-800/20 rounded-xl shimmer-loading" />
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => <div key={i} className="h-[90px] bg-slate-800/20 rounded-xl shimmer-loading" />)}
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="space-y-4 animate-fade-in">
        <Link href="/incidents">
          <Button variant="ghost" size="sm" className="text-slate-500 hover:text-slate-300 h-7 text-[11px]">
            <ArrowLeft className="h-3 w-3 mr-1.5" /> Incidents
          </Button>
        </Link>
        <Card className="border-red-500/15 bg-red-950/5">
          <CardContent className="p-6 text-center">
            <ServerCrash className="h-7 w-7 text-red-400 mx-auto mb-2" />
            <p className="text-xs text-red-400">{error ?? "Incident not found"}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const incident = data?.incident;
  const trace = data?.trace ?? [];
  const auditLog = data?.audit_log ?? [];
  const metricsSnapshot = (incident?.metadata as { metrics_snapshot?: Record<string, number> })?.metrics_snapshot;

  return (
    <div className="space-y-4 animate-fade-in">
      <Link href="/incidents" className="-mt-2 block">
        <Button variant="ghost" size="sm" className="text-slate-500 hover:text-slate-300 h-7 text-[11px]">
          <ArrowLeft className="h-3 w-3 mr-1.5" /> Incidents
        </Button>
      </Link>

      {incident && (
        <Card className={cn("overflow-hidden border-t-2 bg-slate-900/40 backdrop-blur-md",
          incident.severity === 'critical' ? 'border-red-500/50' :
            incident.severity === 'high' ? 'border-orange-500/50' :
              incident.severity === 'medium' ? 'border-yellow-500/50' : 'border-emerald-500/50'
        )}>
          <CardContent className="p-6">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-8">
              <div className="space-y-3">
                <div className="flex items-center gap-3">
                  <Badge className={cn("px-2 py-0.5 rounded text-[10px] font-bold tracking-tighter uppercase -translate-y-[1px]", statusBadgeStyles(incident?.status))}>
                    {incident?.status}
                  </Badge>
                  <div className="flex items-center gap-2 text-slate-500 text-[11px] font-mono">
                    <Clock className="h-3 w-3" />
                    <span>DETECTION AT: {timeStr(incident?.detected_at || trace[0]?.timestamp)}</span>
                  </div>
                </div>
                <h1 className="text-2xl md:text-3xl font-black text-white tracking-tight leading-none bg-gradient-to-r from-white via-white to-slate-500 bg-clip-text text-transparent">
                  {incident?.title}
                </h1>
                <p className="text-slate-400 text-sm font-medium flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                  Impacted Service: <span className="text-blue-400 font-mono">{(incident?.metadata as Record<string, unknown>)?.service as string || 'system-core'}</span>
                </p>
              </div>

              <div className="flex bg-slate-950/40 rounded-xl border border-slate-800/50 shadow-2xl backdrop-blur-xl shrink-0 md:mr-6 lg:mr-8">
                <div className="px-6 py-3 flex flex-col justify-center relative group/sev min-w-[140px]">
                  <div className="absolute inset-0 bg-gradient-to-br from-white/[0.04] to-transparent pointer-events-none rounded-xl" />
                  <div className="text-[10px] text-slate-500 uppercase tracking-[0.2em] mb-1 font-black flex items-center gap-2">
                    <div className="w-1 h-1 rounded-full bg-slate-700 animate-pulse" />
                    Severity
                  </div>
                  <p className={cn("text-xl font-black uppercase tracking-tighter leading-none text-center",
                    incident.severity === 'critical' ? 'text-red-500 drop-shadow-[0_0_10px_rgba(239,68,68,0.4)]' :
                      incident.severity === 'high' ? 'text-orange-500' :
                        incident.severity === 'medium' ? 'text-yellow-500' : 'text-emerald-500'
                  )}>
                    {incident.severity}
                  </p>
                </div>
              </div>
            </div>

            {metricsSnapshot && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
                {Object.entries(metricsSnapshot)
                  .filter(([key, val]) => val !== null && val !== undefined && !key.includes('gc_pause'))
                  .map(([key, val]) => {
                    const display = val == null ? "--" :
                      key === "error_rate" ? `${(val * 100).toFixed(2)}%` :
                        key === "response_time_ms" ? `${val.toFixed(0)}ms` : `${val.toFixed(1)}%`;

                    // Normalize labels
                    const label = key
                      .replace(/service_/g, "")
                      .replace(/_percent/g, " %")
                      .replace(/_/g, " ")
                      .toUpperCase();

                    const isCritical = (key === 'error_rate' && val > 0.1) ||
                      (key.includes('memory') && val > 85) ||
                      (key.includes('cpu') && val > 80) ||
                      (key === 'response_time_ms' && val > 500);

                    return (
                      <div key={key} className={cn(
                        "group relative p-4 rounded-xl border backdrop-blur-sm transition-all duration-300 hover:-translate-y-1",
                        isCritical ? "bg-red-500/5 border-red-500/20 shadow-red-500/5" : "bg-slate-950/30 border-slate-800/50"
                      )}>
                        <div className="flex justify-between items-start mb-2">
                          <p className="text-[9px] text-slate-500 font-black uppercase tracking-widest">{label}</p>
                          <Activity className={cn("h-3 w-3 transition-colors", isCritical ? "text-red-500" : "text-slate-700")} />
                        </div>
                        <div className="flex items-baseline gap-2">
                          <p className={cn("text-2xl font-mono font-black tracking-tighter tabular-nums", isCritical ? "text-red-400" : "text-slate-200")}>
                            {display}
                          </p>
                        </div>
                        <div className="mt-3 h-1 w-full bg-slate-800/50 rounded-full overflow-hidden">
                          <div
                            className={cn("h-full rounded-full transition-all duration-1000", isCritical ? "bg-red-500" : "bg-blue-500")}
                            style={{ width: `${Math.min(100, typeof val === 'number' ? (key.includes('percent') ? val : key.includes('time') ? (val / 10) : 0) : 0)}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_400px] gap-6 mt-6">
        {/* Timeline */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-black text-slate-100 uppercase tracking-tighter flex items-center gap-2">
              <Activity className="h-5 w-5 text-blue-500" />
              Agent Intelligence Trace
            </h2>
            <div className="h-px flex-1 bg-gradient-to-r from-slate-800 to-transparent mx-4" />
          </div>

          {trace.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 bg-slate-900/20 border border-dashed border-slate-800 rounded-2xl">
              <div className="w-12 h-12 rounded-full bg-slate-800/50 flex items-center justify-center mb-4">
                <Brain className="h-6 w-6 text-slate-600" />
              </div>
              <p className="text-sm font-medium text-slate-500">No trace data available for this incident lifecycle.</p>
            </div>
          ) : (
            <div className="relative pl-12 space-y-8">
              {/* Central vertical line - Precision aligned and extended for continuity */}
              <div className="absolute left-[19px] top-6 bottom-[-20px] w-[2px] bg-gradient-to-b from-blue-500 via-yellow-500 via-orange-500 to-emerald-500 opacity-60 shadow-[0_0_10px_rgba(59,130,246,0.3)]" />

              {trace.map((step, i) => {
                if (!step) return null;
                const meta = AGENT_META[step.agent_name] || AGENT_META.watcher;
                const Icon = meta.icon;
                const reasoning = parseReasoning(step.reasoning);

                return (
                  <div key={i} className="relative group animate-slide-up" style={{ animationDelay: `${i * 100}ms` }}>
                    {/* Timeline Node - Precision centring with vertical trace line */}
                    <div className={cn(
                      "absolute -left-[48px] w-10 h-10 rounded-xl flex items-center justify-center ring-4 ring-slate-950 transition-all duration-300 z-10",
                      meta.bgColor,
                      "shadow-[0_0_20px_rgba(0,0,0,0.5)] group-hover:scale-110",
                      "border border-white/10"
                    )} style={{ top: "14px" }}>
                      <Icon className="h-5 w-5 text-white" />
                    </div>

                    <Card className={cn(
                      "overflow-hidden border backdrop-blur-sm bg-slate-900/60 transition-all duration-300 hover:bg-slate-900/80 hover:border-slate-700 shadow-xl",
                      meta.borderColor
                    )}>
                      <CardContent className="p-5">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
                          <div className="flex items-center gap-3">
                            <div>
                              <p className="text-[10px] font-black uppercase tracking-[0.2em] mb-0.5 opacity-50" style={{ color: meta.color }}>
                                {meta.label} Phase
                              </p>
                              <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                                {step.decision_type.toUpperCase()}
                                {step.confidence != null && (
                                  <span className="text-[10px] bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded border border-slate-700 ml-2">
                                    {(step.confidence * 100).toFixed(0)}% CONFIDENCE
                                  </span>
                                )}
                              </h3>
                            </div>
                          </div>
                          <div className="flex items-center gap-2 text-[10px] font-mono text-slate-500 bg-slate-950/50 px-2 py-1 rounded border border-slate-800/50">
                            <Clock className="h-3 w-3" />
                            {timeStr(step.timestamp)}
                          </div>
                        </div>

                        <div className="space-y-4">
                          {typeof reasoning.summary === "string" && reasoning.summary && (
                            <div className="p-3 bg-white/[0.03] border border-white/[0.05] rounded-xl">
                              <p className="text-xs leading-relaxed text-slate-300 italic">&quot;{reasoning.summary}&quot;</p>
                            </div>
                          )}

                          {typeof reasoning.root_cause === "string" && reasoning.root_cause && (
                            <div className="flex gap-3 p-4 bg-yellow-500/5 border border-yellow-500/10 rounded-xl relative overflow-hidden group/rc">
                              <div className="absolute left-0 top-0 bottom-0 w-1 bg-yellow-500/50" />
                              <Brain className="h-5 w-5 text-yellow-500/50 shrink-0" />
                              <div>
                                <p className="text-[10px] font-black text-yellow-500/30 uppercase tracking-widest mb-1">Diagnosis Confirmed</p>
                                <p className="text-sm font-bold text-slate-200">{String(reasoning.root_cause_category || reasoning.root_cause)}</p>
                                {typeof reasoning.confidence === "number" && (
                                  <div className="mt-2 h-1 w-32 bg-slate-800 rounded-full overflow-hidden">
                                    <div className="h-full bg-yellow-500" style={{ width: `${reasoning.confidence * 100}%` }} />
                                  </div>
                                )}
                              </div>
                            </div>
                          )}

                          {(Array.isArray(reasoning.execution_results) || Array.isArray(reasoning.pending_actions)) && (
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                              {Array.isArray(reasoning.execution_results) && (
                                <div className="space-y-2">
                                  <p className="text-[9px] font-bold text-slate-500 uppercase tracking-widest">Completed Operations</p>
                                  <div className="flex flex-wrap gap-2">
                                    {(reasoning.execution_results as Array<{ tool?: string; action?: string; status?: string }>).map((r, j) => (
                                      <Badge key={j} variant="outline" className="px-2 py-1 rounded bg-emerald-500/5 border-emerald-500/20 text-emerald-400 text-[10px] font-mono">
                                        <Check className="h-2.5 w-2.5 mr-1" />
                                        {r.tool || r.action}
                                      </Badge>
                                    ))}
                                  </div>
                                </div>
                              )}
                              {Array.isArray(reasoning.pending_actions) && (
                                <div className="space-y-2">
                                  <p className="text-[9px] font-bold text-slate-500 uppercase tracking-widest">Pending Validations</p>
                                  <div className="flex flex-wrap gap-2">
                                    {(reasoning.pending_actions as Array<{ tool?: string; action?: string }>).map((r, j) => (
                                      <Badge key={j} variant="outline" className="px-2 py-1 rounded bg-orange-500/5 border-orange-500/20 text-orange-400 text-[10px] font-mono">
                                        <Zap className="h-2.5 w-2.5 mr-1" />
                                        {r.tool || r.action}
                                      </Badge>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          )}

                          <div className="flex gap-2 pt-2">
                            {step.tool_calls && (step.tool_calls as unknown[]).length > 0 && (
                              <ExpandableSection title={`View Intelligence Data (${(step.tool_calls as unknown[]).length})`}>
                                <div className="grid grid-cols-1 gap-2">
                                  {(step.tool_calls as Array<{ tool?: string; server?: string; result_summary?: string }>).map((tc, j) => (
                                    <div key={j} className="flex items-center justify-between p-2 bg-slate-950/30 rounded border border-slate-800/50">
                                      <div className="flex items-center gap-2">
                                        <code className="text-blue-400 font-bold">{tc.tool}</code>
                                        <span className="text-[10px] text-slate-600 font-mono">[{tc.server}]</span>
                                      </div>
                                      <span className="text-slate-400 italic">&quot;{tc.result_summary}&quot;</span>
                                    </div>
                                  ))}
                                </div>
                              </ExpandableSection>
                            )}
                            <ExpandableSection title="Technical Reasoning">
                              <pre className="p-4 bg-slate-950 rounded-xl border border-slate-800 font-mono text-[10px] leading-relaxed text-blue-400/80 overflow-auto max-h-[300px]">
                                {JSON.stringify(reasoning, null, 2)}
                              </pre>
                            </ExpandableSection>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="space-y-6">
          <section>
            <h2 className="text-[13px] font-bold text-slate-300 mb-4">
              Unified Operations Feed
            </h2>
            <Card className="bg-slate-900/40 border-slate-800/80 overflow-hidden shadow-2xl">
              <ScrollArea className="h-[600px]">
                <div className="p-1">
                  {auditLog.length === 0 ? (
                    <div className="py-20 text-center">
                      <p className="text-xs text-slate-600 font-mono">NO LOG ENTRIES RECORDED</p>
                    </div>
                  ) : (
                    <div className="divide-y divide-slate-800/50">
                      {auditLog.map((log, i) => {
                        const meta = AGENT_META[log.agent_name];
                        return (
                          <div key={i} className="p-3 hover:bg-white/[0.02] transition-colors group">
                            <div className="flex items-center justify-between mb-1">
                              <div className="flex items-center gap-2">
                                <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: meta?.color ?? "#94a3b8" }} />
                                <span className="text-[10px] font-black uppercase tracking-tighter" style={{ color: meta?.color ?? "#94a3b8" }}>
                                  {log.agent_name}
                                </span>
                              </div>
                              <span className="text-[9px] font-mono text-slate-600 tabular-nums">{timeStr(log.timestamp)}</span>
                            </div>
                            <p className="text-[11px] text-slate-300 font-mono line-clamp-2 mt-1 group-hover:text-white transition-colors">
                              {log.tool_name || log.action}
                            </p>
                            <p className="text-[9px] text-slate-600 mt-1 uppercase tracking-widest font-bold font-mono">
                              PATH: <span className="text-slate-500">{log.mcp_server || "internal"}</span>
                            </p>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </ScrollArea>
            </Card>
          </section>

          {events && events.events.length > 0 && (
            <section className="animate-fade-in delay-200">
              <h2 className="text-[13px] font-bold text-slate-300 mb-3 flex items-center gap-2">
                <Clock className="h-4 w-4 text-slate-500" />
                Lifecycle Milestone Events
              </h2>
              <div className="space-y-2">
                {[...events.events].reverse().map((evt) => (
                  <div key={evt.id} className="relative pl-4 py-2 bg-slate-900/30 rounded-lg border border-slate-800/50 group">
                    <div className="absolute left-0 top-0 bottom-0 w-1 bg-blue-500/20 group-hover:bg-blue-500/50 transition-colors" />
                    <div className="flex items-center justify-between mb-1">
                      <Badge variant="outline" className="text-[8px] font-mono border-slate-700 bg-slate-950 text-slate-400 h-4 uppercase tracking-tighter">{evt.event_type}</Badge>
                      <span className="text-[9px] font-mono text-slate-600 tabular-nums">{timeStr(evt.created_at)}</span>
                    </div>
                    <p className="text-[10px] text-slate-400 font-medium truncate">
                      {evt.event_type === "status_transition"
                        ? `Lifecycle transition: ${(evt.payload as { from?: string }).from} to ${(evt.payload as { to?: string }).to}`
                        : `Remediation approved: ${(evt.payload as Record<string, unknown>).tool as string || 'action'}`}
                    </p>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
