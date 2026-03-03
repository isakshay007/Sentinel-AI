"use client";

import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  api,
  type ApprovalRequest,
  type Incident,
  type AgentDecision,
  type ServiceHealth,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Check, X, CheckCircle2, AlertTriangle, Loader2, Clock, Ban,
} from "lucide-react";
import { toast } from "sonner";

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "--";
  const sec = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

function parseReasoning(raw: string | undefined): Record<string, unknown> {
  if (!raw) return {};
  try {
    const p = JSON.parse(raw);
    if (typeof p === "object" && p !== null) return p as Record<string, unknown>;
  } catch { /* ignore */ }
  return {};
}

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [history, setHistory] = useState<ApprovalRequest[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [decisions, setDecisions] = useState<AgentDecision[]>([]);
  const [services, setServices] = useState<ServiceHealth[]>([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState<string | null>(null);

  const fetchAll = () => {
    Promise.all([
      api.getApprovals().catch(() => null),
      api.getApprovalHistory().catch(() => ({ total: 0, pending: 0, approved: 0, rejected: 0, history: [] })),
      api.getIncidents().catch(() => null),
      api.getAgentDecisions(undefined, 50).catch(() => null),
      api.getServiceHealth().catch(() => null),
    ])
      .then(([app, hist, inc, dec, svc]) => {
        setApprovals(app?.approvals ?? []);
        setHistory((hist?.history ?? []).filter((h) => h.status !== "pending"));
        setIncidents(inc?.incidents ?? []);
        setDecisions(dec?.decisions ?? []);
        setServices(svc?.services ?? []);
      })
      .catch(() => { })
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchAll(); }, []);
  useEffect(() => { const id = setInterval(fetchAll, 3000); return () => clearInterval(id); }, []);
  useEffect(() => {
    const handler = () => fetchAll();
    window.addEventListener("approvals-updated", handler);
    window.addEventListener("execution-completed", handler);
    return () => {
      window.removeEventListener("approvals-updated", handler);
      window.removeEventListener("execution-completed", handler);
    };
  }, []);

  const handleApprove = async (req: ApprovalRequest) => {
    setProcessing(req.id);
    try {
      const res = await api.approve(req.id);
      toast.success(res.incident_resolved ? "Approved — incident resolved!" : "Approved — action executed");
      setApprovals((prev) => prev.filter((a) => a.id !== req.id));
      window.dispatchEvent(new CustomEvent("execution-completed", { detail: { incident_id: res.incident_id } }));
    } catch {
      toast.error("Failed to approve");
    } finally {
      setProcessing(null);
    }
  };

  const handleReject = async (req: ApprovalRequest) => {
    setProcessing(req.id);
    try {
      await api.reject(req.id);
      toast.success("Action rejected");
      setApprovals((prev) => prev.filter((a) => a.id !== req.id));
      window.dispatchEvent(new CustomEvent("approvals-updated"));
    } catch {
      toast.error("Failed to reject");
    } finally {
      setProcessing(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4 stagger-children">
        <div className="h-10 w-48 bg-slate-900/40 border border-slate-800/30 rounded-xl animate-pulse" />
        {[...Array(3)].map((_, i) => <div key={i} className="h-40 bg-slate-900/40 border border-slate-800/20 rounded-xl animate-pulse" />)}
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in relative">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex flex-col">
          <h1 className="text-[18px] font-black uppercase tracking-[0.3em] text-white">Manual Authorization Center</h1>
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mt-1">Strategic Overrides & High-Risk Protocol Execution</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex flex-col items-end">
            <span className="text-[10px] font-black uppercase tracking-widest text-slate-600">Active Requests</span>
            <span className={cn(
              "text-lg font-black tabular-nums transition-colors",
              approvals.length > 0 ? "text-red-500 drop-shadow-[0_0_8px_rgba(239,68,68,0.4)]" : "text-emerald-500"
            )}>
              {approvals.length}
            </span>
          </div>
        </div>
      </div>

      {/* Pending Section */}
      <div className="space-y-4">

        {approvals.length === 0 ? (
          <Card className="bg-slate-900/40 backdrop-blur-xl border-emerald-500/10 shadow-2xl overflow-hidden relative group">
            <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 via-transparent to-transparent opacity-50" />
            <CardContent className="py-16 text-center relative z-10">
              <div className="w-16 h-16 rounded-full bg-emerald-500/5 flex items-center justify-center mx-auto mb-4 border border-emerald-500/10 shadow-lg">
                <CheckCircle2 className="h-8 w-8 text-emerald-500/40" />
              </div>
              <p className="text-sm font-black text-emerald-400/80 uppercase tracking-[0.2em]">Deployment Secure</p>
              <p className="text-[10px] text-slate-600 mt-2 uppercase tracking-widest font-bold">No manual intervention required at this interval</p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-4">
            {approvals.map((req) => {
              const pendingMs = Date.now() - new Date(req.requested_at).getTime();
              const pendingMin = pendingMs / 60000;
              const incident = incidents.find((i) => i.id === req.incident_id);
              const incDecisions = decisions.filter((d) => d.incident_id === req.incident_id);
              const watcherD = incDecisions.find((d) => d.agent_name === "watcher");
              const diagD = incDecisions.find((d) => d.agent_name === "diagnostician");
              const stratD = incDecisions.find((d) => d.agent_name === "strategist");
              const currentSvc = services.find((s) => s.name === req.service);

              const watcherR = watcherD ? parseReasoning(watcherD.reasoning) : null;
              const diagR = diagD ? parseReasoning(diagD.reasoning) : null;
              const stratR = stratD ? parseReasoning(stratD.reasoning) : null;

              const isUrgent = pendingMin > 2;

              return (
                <Card
                  key={req.id}
                  className={cn(
                    "bg-slate-900/60 backdrop-blur-2xl border-2 transition-all duration-500 shadow-2xl relative overflow-hidden group",
                    isUrgent ? "border-red-500/30 animate-glow-red" : "border-yellow-500/20"
                  )}
                >
                  <div className={cn("absolute top-0 left-0 bottom-0 w-1 shadow-lg", isUrgent ? "bg-red-500 animate-pulse" : "bg-yellow-500")} />
                  <CardContent className="p-5 space-y-5 relative z-10">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className={cn(
                          "w-10 h-10 rounded-xl flex items-center justify-center border shadow-lg transition-transform duration-500 group-hover:scale-110",
                          isUrgent ? "bg-red-500/10 border-red-500/20 text-red-500" : "bg-yellow-500/10 border-yellow-500/20 text-yellow-500"
                        )}>
                          <AlertTriangle className="h-5 w-5 animate-pulse" />
                        </div>
                        <div>
                          <p className="text-[13px] font-black text-white uppercase tracking-[0.2em]">Protocol Entry: {req.tool}</p>
                          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mt-0.5">Authorization ID: <span className="font-mono text-[9px] opacity-70">{req.id.slice(0, 8)}</span></p>
                        </div>
                      </div>
                      <div className="flex flex-col items-end shrink-0">
                        <div className="flex items-center gap-1.5 text-[10px] font-black tabular-nums text-slate-500 uppercase tracking-widest">
                          <Clock className="h-3 w-3" />
                          {timeAgo(req.requested_at)}
                        </div>
                        <Badge className={cn(
                          "mt-1 text-[9px] font-black uppercase tracking-[0.2em] h-5 px-2 border-none shadow-md",
                          req.risk_level === "risky" ? "bg-red-600 text-white" : "bg-emerald-600 text-white"
                        )}>
                          {req.risk_level}
                        </Badge>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="p-3.5 rounded-xl bg-slate-950/50 border border-slate-800/50 space-y-2 relative group-hover:bg-slate-950/80 transition-colors">
                        <p className="text-[9px] font-black uppercase tracking-[0.2em] text-slate-500">Incident Intelligence</p>
                        <p className="text-[12px] text-slate-300 leading-relaxed font-medium">
                          {(watcherR?.summary as string) || (incident?.title) || "Autonomous signal detected an anomaly requires manual confirmation"}
                        </p>
                      </div>

                      <div className="p-3.5 rounded-xl bg-slate-950/50 border border-slate-800/50 space-y-2 relative group-hover:bg-slate-950/80 transition-colors">
                        <p className="text-[9px] font-black uppercase tracking-[0.2em] text-slate-500">Root Cause Signature</p>
                        <div>
                          <p className="text-[12px] font-black uppercase tracking-widest text-yellow-400 drop-shadow-[0_0_8px_rgba(234,179,8,0.3)]">
                            {(diagR?.root_cause_category as string) || (diagR?.root_cause as string) || (incident?.root_cause) || "Analyzing Vector..."}
                          </p>
                          {typeof diagR?.confidence === "number" && (
                            <div className="flex items-center gap-2 mt-2">
                              <div className="flex-1 h-1 bg-slate-800 rounded-full overflow-hidden">
                                <div className="h-full bg-yellow-500 rounded-full" style={{ width: `${diagR.confidence * 100}%` }} />
                              </div>
                              <span className="text-[10px] font-black tabular-nums text-slate-600">{(diagR.confidence * 100).toFixed(0)}% CONF</span>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-4 bg-slate-950/30 p-3 rounded-xl border border-white/[0.03]">
                      <div className="flex flex-col gap-1">
                        <span className="text-[9px] font-black text-slate-600 uppercase tracking-widest">Parameters</span>
                        <code className="text-[10px] text-blue-400 font-mono bg-blue-500/5 px-2 py-0.5 rounded border border-blue-500/10">
                          {JSON.stringify(req.tool_args)}
                        </code>
                      </div>

                      {currentSvc && (
                        <div className="flex gap-4 ml-auto border-l border-slate-800/50 pl-4 py-1">
                          {[
                            { label: "CPU", val: currentSvc.cpu_percent, critical: 80, fmt: (v: number) => `${v.toFixed(1)}%` },
                            { label: "MEM", val: currentSvc.memory_percent, critical: 85, fmt: (v: number) => `${v.toFixed(1)}%` },
                            { label: "LAT", val: currentSvc.response_time_ms, critical: 500, fmt: (v: number) => `${v.toFixed(0)}ms` },
                          ].map(m => (
                            <div key={m.label} className="flex flex-col items-end">
                              <span className="text-[9px] font-black text-slate-600 uppercase tracking-widest">{m.label}</span>
                              <span className={cn("text-[11px] font-black tabular-nums tracking-tighter", m.val > m.critical ? "text-red-400 animate-pulse" : "text-emerald-400")}>{m.fmt(m.val)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="flex items-center justify-end gap-3 pt-1">
                      <Button
                        variant="ghost"
                        onClick={() => handleReject(req)}
                        disabled={processing === req.id}
                        className="text-slate-500 hover:text-red-400 hover:bg-red-500/10 h-10 px-8 text-[11px] font-black uppercase tracking-[0.2em] transition-all"
                      >
                        <X className="h-4 w-4 mr-2" /> Abort Protocol
                      </Button>
                      <Button
                        onClick={() => handleApprove(req)}
                        disabled={processing === req.id}
                        className="bg-emerald-600 hover:bg-emerald-500 text-white h-10 px-10 rounded-lg text-[11px] font-black uppercase tracking-[0.25em] shadow-[0_0_20px_rgba(5,150,105,0.3)] hover:scale-[1.02] active:scale-[0.98] transition-all"
                      >
                        {processing === req.id ? (
                          <Loader2 className="h-4 w-4 animate-spin mr-2" />
                        ) : (
                          <Check className="h-4 w-4 mr-2" />
                        )}
                        Authorize Execution
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>

      {/* History Section */}
      <div className="space-y-4 pt-4">
        <div className="flex items-center gap-3">
          <span className="h-[1px] flex-1 bg-gradient-to-r from-transparent via-slate-800/50 to-transparent" />
          <h2 className="text-[11px] font-black uppercase tracking-[0.4em] text-slate-500">Operation Archive</h2>
          <span className="h-[1px] flex-1 bg-gradient-to-r from-transparent via-slate-800/50 to-transparent" />
        </div>

        <Card className="bg-slate-900/40 backdrop-blur-xl border-slate-800/50 shadow-2xl overflow-hidden">
          <CardContent className="p-0">
            <ScrollArea className="h-full max-h-[500px]">
              <Table>
                <TableHeader className="bg-slate-950/50 border-b border-slate-800/50">
                  <TableRow className="border-none hover:bg-transparent">
                    <TableHead className="text-[10px] font-black text-slate-500 uppercase h-10 tracking-widest pl-6">Signature</TableHead>
                    <TableHead className="text-[10px] font-black text-slate-500 uppercase h-10 tracking-widest text-center">Status</TableHead>
                    <TableHead className="text-[10px] font-black text-slate-500 uppercase h-10 tracking-widest">Protocol</TableHead>
                    <TableHead className="text-[10px] font-black text-slate-500 uppercase h-10 tracking-widest">Domain</TableHead>
                    <TableHead className="text-[10px] font-black text-slate-500 uppercase h-10 tracking-widest">Time</TableHead>
                    <TableHead className="text-[10px] font-black text-slate-500 uppercase h-10 tracking-widest text-right pr-6">Operator</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {history.map((h) => (
                    <TableRow key={h.id} className="border-slate-800/30 hover:bg-white/[0.02] transition-colors border-b">
                      <TableCell className="pl-6 font-mono text-[10px] text-slate-600 uppercase">#{h.id.slice(0, 8)}</TableCell>
                      <TableCell className="text-center">
                        {h.status === "approved" && <Badge variant="outline" className="text-[9px] font-black border-emerald-500/20 text-emerald-400 bg-emerald-500/5 h-5 px-1.5"><Check className="h-2.5 w-2.5 mr-1" />Approved</Badge>}
                        {h.status === "rejected" && <Badge variant="outline" className="text-[9px] font-black border-red-500/20 text-red-400 bg-red-500/5 h-5 px-1.5"><X className="h-2.5 w-2.5 mr-1" />Rejected</Badge>}
                        {h.status === "cancelled" && <Badge variant="outline" className="text-[9px] font-black border-slate-500/20 text-slate-400 bg-slate-500/5 h-5 px-1.5"><Ban className="h-2.5 w-2.5 mr-1" />Cancelled</Badge>}
                      </TableCell>
                      <TableCell className="text-[11px] text-slate-300 font-bold uppercase tracking-wider">{h.tool}</TableCell>
                      <TableCell className="text-[11px] text-blue-400 font-mono tracking-tighter">{h.service}</TableCell>
                      <TableCell className="text-[10px] text-slate-500 tabular-nums uppercase font-bold">{timeAgo(h.decided_at)}</TableCell>
                      <TableCell className="text-right pr-6 text-[10px] text-slate-500 font-black uppercase tracking-widest">{h.decided_by || "System"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </ScrollArea>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
