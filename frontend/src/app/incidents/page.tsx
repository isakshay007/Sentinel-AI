"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { api, type Incident } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ShieldCheck, Clock, AlertTriangle, ServerCrash } from "lucide-react";

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "--";
  const sec = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

function formatDuration(detectedAt: string | null | undefined, resolvedAt: string | null | undefined): string {
  if (!detectedAt) return "--";
  if (!resolvedAt) return "ongoing";
  const ms = new Date(resolvedAt).getTime() - new Date(detectedAt).getTime();
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
}

function severityColor(s: string | undefined): string {
  switch (s) {
    case "critical": return "bg-red-500/15 text-red-400 border-red-500/20";
    case "high": return "bg-orange-500/15 text-orange-400 border-orange-500/20";
    case "medium": return "bg-yellow-500/15 text-yellow-400 border-yellow-500/20";
    case "low": return "bg-emerald-500/15 text-emerald-400 border-emerald-500/20";
    default: return "bg-slate-500/15 text-slate-400 border-slate-500/20";
  }
}

function statusBadge(s: string | undefined) {
  switch (s) {
    case "open": return "bg-red-500/10 text-red-400 border-red-500/15";
    case "investigating": return "bg-yellow-500/10 text-yellow-400 border-yellow-500/15";
    case "resolved": return "bg-emerald-500/10 text-emerald-400 border-emerald-500/15";
    default: return "bg-slate-500/10 text-slate-400 border-slate-500/15";
  }
}

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchIncidents = useCallback(() => {
    const status = statusFilter === "all" ? undefined : statusFilter;
    api
      .getIncidents(status)
      .then((r) => {
        setIncidents(r?.incidents ?? []);
        setError(null);
      })
      .catch((e) => {
        setError(e?.message ?? "Failed to fetch incidents");
        setIncidents([]);
      })
      .finally(() => setLoading(false));
  }, [statusFilter]);

  useEffect(() => { fetchIncidents(); }, [fetchIncidents]);
  useEffect(() => { const id = setInterval(fetchIncidents, 5000); return () => clearInterval(id); }, [fetchIncidents]);
  useEffect(() => {
    const handler = () => fetchIncidents();
    window.addEventListener("execution-completed", handler);
    return () => window.removeEventListener("execution-completed", handler);
  }, [fetchIncidents]);

  const renderList = () => {
    if (loading) {
      return (
        <div className="space-y-3">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-16 bg-slate-900/40 border border-slate-800/30 rounded-xl animate-pulse" />
          ))}
        </div>
      );
    }

    if (error) {
      return (
        <div className="py-20 text-center animate-fade-in bg-red-950/5 border border-red-500/10 rounded-2xl">
          <ServerCrash className="h-10 w-10 text-red-500/40 mx-auto mb-4" />
          <p className="text-sm font-bold text-red-400 uppercase tracking-widest">{error}</p>
          <p className="text-[10px] text-slate-600 mt-2 uppercase tracking-widest">Re-establishing connection...</p>
        </div>
      );
    }

    if (!incidents || incidents.length === 0) {
      return (
        <div className="py-24 text-center animate-fade-in bg-slate-900/20 border border-white/[0.03] rounded-2xl">
          <div className="w-16 h-16 rounded-full bg-emerald-500/5 flex items-center justify-center mx-auto mb-4 border border-emerald-500/10">
            <ShieldCheck className="h-8 w-8 text-emerald-500/30" />
          </div>
          <p className="text-sm font-bold text-slate-400 uppercase tracking-[0.2em]">
            {statusFilter === "all"
              ? "Mission Log Empty"
              : statusFilter === "open"
                ? "All Systems Green"
                : "No Archived Incidents"}
          </p>
          <p className="text-[10px] text-slate-600 mt-2 uppercase tracking-widest font-bold">Scanning for anomalies...</p>
        </div>
      );
    }

    return (
      <div className="grid grid-cols-1 gap-3">
        {incidents.map((inc, idx) => {
          if (!inc) return null;
          const service = (inc.metadata as { service?: string })?.service ?? "N/A";
          const isResolved = inc.status === "resolved";

          return (
            <Link key={inc.id ?? idx} href={`/incidents/${inc.id}`}>
              <Card
                className={cn(
                  "bg-slate-900/60 backdrop-blur-xl border-slate-800/50 hover:border-slate-700/80 transition-all duration-300 card-interactive cursor-pointer group relative overflow-hidden",
                  !isResolved && inc.severity === "critical" && "border-red-500/30 bg-red-950/10"
                )}
                style={{ animationDelay: `${idx * 40}ms` }}
              >
                {!isResolved && inc.severity === "critical" && (
                  <div className="absolute top-0 left-0 right-0 h-[1px] bg-red-500/50 animate-pulse" />
                )}
                <CardContent className="p-0">
                  <div className="flex items-center gap-4 px-4 py-3.5">
                    <div className={cn(
                      "w-10 h-10 rounded-xl flex items-center justify-center shrink-0 border transition-all duration-500 shadow-lg",
                      isResolved
                        ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400 group-hover:bg-emerald-500/20"
                        : "bg-red-500/10 border-red-500/20 text-red-400 group-hover:bg-red-500/20 animate-pulse"
                    )}>
                      {isResolved ? (
                        <ShieldCheck className="h-5 w-5" />
                      ) : (
                        <AlertTriangle className="h-5 w-5" />
                      )}
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <Badge variant="outline" className={cn(
                          "text-[9px] font-black uppercase tracking-widest h-4 px-1.5 border-none",
                          isResolved ? "bg-emerald-600 text-white" : "bg-red-600 text-white shadow-[0_0_10px_rgba(239,68,68,0.3)]"
                        )}>
                          {inc.status}
                        </Badge>
                        <Badge variant="outline" className={cn(
                          "text-[9px] font-black uppercase tracking-widest h-4 px-1.5 bg-slate-950/40 border-slate-800",
                          severityColor(inc.severity).replace("bg-", "text-").replace("/15", "")
                        )}>
                          {inc.severity}
                        </Badge>
                        <span className="text-[10px] font-mono font-bold text-slate-500 uppercase tracking-widest ml-1">{service}</span>
                      </div>
                      <p className="text-[13px] font-bold text-slate-200 group-hover:text-white transition-colors truncate tracking-tight">{inc.title ?? "Untitled Mission"}</p>
                    </div>

                    <div className="flex flex-col items-end gap-1 shrink-0 ml-4">
                      <div className="flex items-center gap-1.5 text-[10px] font-black tabular-nums text-slate-500 uppercase tracking-widest">
                        <Clock className="h-3 w-3" />
                        {timeAgo(inc.detected_at)}
                      </div>
                      <div className="text-[10px] font-mono text-slate-600 uppercase tracking-widest flex items-center gap-1">
                        <span>Dur:</span>
                        <span className="text-slate-400 font-bold">{formatDuration(inc.detected_at, inc.resolved_at)}</span>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>
    );
  };

  return (
    <div className="space-y-6 animate-fade-in relative">
      <div className="flex items-center justify-between mb-2">
        <div className="flex flex-col">
          <h1 className="text-[18px] font-black uppercase tracking-[0.3em] text-white">Incident Log</h1>
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mt-1">Passive Surveillance History & Active Breaches</p>
        </div>

        <Tabs value={statusFilter} onValueChange={setStatusFilter} className="w-auto">
          <TabsList className="bg-slate-950/50 backdrop-blur-md h-9 gap-1 p-1 border border-white/[0.03] shadow-2xl">
            <TabsTrigger value="all" className="text-[10px] h-7 px-5 font-black uppercase tracking-widest data-[state=active]:bg-blue-600 data-[state=active]:text-white transition-all">All Logs</TabsTrigger>
            <TabsTrigger value="open" className="text-[10px] h-7 px-5 font-black uppercase tracking-widest data-[state=active]:bg-red-600 data-[state=active]:text-white transition-all">Open</TabsTrigger>
            <TabsTrigger value="resolved" className="text-[10px] h-7 px-5 font-black uppercase tracking-widest data-[state=active]:bg-emerald-600 data-[state=active]:text-white transition-all">Resolved</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <div className="relative min-h-[400px]">
        {renderList()}
        <div className="absolute -bottom-10 left-0 right-0 h-20 bg-gradient-to-t from-black/20 to-transparent pointer-events-none" />
      </div>
    </div>
  );
}
