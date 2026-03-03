"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { api, type Incident } from "@/lib/api";
import { cn } from "@/lib/utils";

function severityStripColor(s: string): string {
  switch (s) {
    case "critical": return "#DC2626";
    case "high": return "#F97316";
    case "medium": return "#EAB308";
    case "low": return "#10B981";
    default: return "#94A3B8";
  }
}

function severityLabel(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function timeAgo(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  const sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return "Just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

function IncidentCard({ inc, highlight }: { inc: Incident; highlight?: boolean }) {
  const service = (inc.metadata as { service?: string })?.service ?? "—";
  const stripColor = severityStripColor(inc.severity);

  return (
    <Link href={`/incidents/${inc.id}`}>
      <Card
        className={cn(
          "hover:bg-accent/50 transition-all duration-300 cursor-pointer overflow-hidden shadow-[0_1px_2px_rgba(0,0,0,0.05)] border-[#E5E7EB]",
          highlight && "ring-2 ring-emerald-500/60 ring-offset-2 animate-[fadeGlow_2s_ease-out]"
        )}
      >
        <div className="flex">
          <div
            className="w-1 shrink-0"
            style={{ backgroundColor: stripColor, minWidth: 4 }}
          />
          <CardContent className="flex items-start justify-between gap-4 p-5 flex-1 min-w-0">
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">
                {severityLabel(inc.severity)}
              </p>
              <p className="text-[16px] font-semibold mb-1 truncate">{inc.title}</p>
              <p className="text-[15px] text-muted-foreground mb-2 line-clamp-2">
                {(() => {
                  const meta = inc.metadata as { summary?: string; description?: string };
                  const desc = meta?.summary || meta?.description || inc.root_cause || "No details";
                  const titleLower = (inc.title || "").toLowerCase();
                  const descLower = desc.toLowerCase();
                  if (desc && titleLower && (titleLower.includes(descLower.slice(0, 30)) || descLower.includes(titleLower.slice(0, 30)))) {
                    return meta?.description || "View incident for full analysis";
                  }
                  return desc;
                })()}
              </p>
              <p className="text-[13px] text-muted-foreground">
                {service} • {timeAgo(inc.detected_at)}
              </p>
            </div>
            <Badge variant="secondary" className="shrink-0 text-[13px] font-medium">
              {inc.status}
            </Badge>
          </CardContent>
        </div>
      </Card>
    </Link>
  );
}

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [highlightId, setHighlightId] = useState<string | null>(null);

  const fetchIncidents = useCallback(() => {
    setLoading(true);
    const status = statusFilter === "all" ? undefined : statusFilter;
    api
      .getIncidents(status)
      .then((r) => setIncidents(r.incidents))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [statusFilter]);

  useEffect(() => {
    // Initial load; safe to invoke fetchIncidents here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchIncidents();
  }, [fetchIncidents]);

  useEffect(() => {
    const id = setInterval(fetchIncidents, 5000);
    return () => clearInterval(id);
  }, [fetchIncidents]);

  useEffect(() => {
    const handler = (e: Event) => {
      fetchIncidents();
      const incidentId = (e as CustomEvent<{ incidentId?: string }>)?.detail?.incidentId;
      if (incidentId) {
        setHighlightId(incidentId);
        setTimeout(() => setHighlightId(null), 2500);
      }
    };
    window.addEventListener("scenario-completed", handler);
    return () => window.removeEventListener("scenario-completed", handler);
  }, [fetchIncidents]);

  useEffect(() => {
    const handler = () => fetchIncidents();
    window.addEventListener("execution-completed", handler);
    return () => window.removeEventListener("execution-completed", handler);
  }, [fetchIncidents]);

  const list = (
    <div className="space-y-4">
      {incidents.map((inc) => (
        <IncidentCard key={inc.id} inc={inc} highlight={highlightId === inc.id} />
      ))}
    </div>
  );

  return (
    <div className="space-y-8" style={{ gap: "var(--spacing-section, 32px)" }}>
      <h1 className="text-page-title">Incidents</h1>

      <Tabs value={statusFilter} onValueChange={setStatusFilter}>
        <TabsList>
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="open">Open</TabsTrigger>
          <TabsTrigger value="resolved">Resolved</TabsTrigger>
        </TabsList>
        <TabsContent value="all" className="mt-6">
          {loading ? (
            <p className="text-muted-foreground text-[15px]">Loading...</p>
          ) : incidents.length === 0 ? (
            <p className="text-muted-foreground text-[15px]">No incidents</p>
          ) : (
            list
          )}
        </TabsContent>
        <TabsContent value="open" className="mt-6">
          {loading ? (
            <p className="text-muted-foreground text-[15px]">Loading...</p>
          ) : incidents.length === 0 ? (
            <p className="text-muted-foreground text-[15px]">No open incidents. Inject a fault to trigger the agent pipeline, or view All/Resolved tabs.</p>
          ) : (
            list
          )}
        </TabsContent>
        <TabsContent value="resolved" className="mt-6">
          {loading ? (
            <p className="text-muted-foreground text-[15px]">Loading...</p>
          ) : incidents.length === 0 ? (
            <p className="text-muted-foreground text-[15px]">No resolved incidents</p>
          ) : (
            list
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
