"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AgentTerminal } from "@/components/agent-terminal";
import { api, type AgentTraceResponse } from "@/lib/api";
import { ArrowLeft, Activity, Brain, Swords, Zap, ChevronDown, ChevronRight } from "lucide-react";

const AGENT_ICONS: Record<string, React.ElementType> = {
  watcher: Activity,
  diagnostician: Brain,
  strategist: Swords,
  executor: Zap,
};

function ExpandableSection({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border rounded-lg">
      <button
        type="button"
        className="w-full flex items-center gap-2 p-3 text-left hover:bg-accent/50"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <span className="font-medium">{title}</span>
      </button>
      {open && <div className="p-3 pt-0 border-t text-sm font-mono bg-muted/30">{children}</div>}
    </div>
  );
}

export default function AgentTracePage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [data, setData] = useState<AgentTraceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTrace = useCallback(() => {
    api
      .getAgentTrace(id)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    fetchTrace();
  }, [fetchTrace]);

  useEffect(() => {
    const id = setInterval(fetchTrace, 15000);
    return () => clearInterval(id);
  }, [fetchTrace]);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ incident_id?: string }>)?.detail;
      if (detail?.incident_id === id) fetchTrace();
    };
    window.addEventListener("execution-completed", handler);
    return () => window.removeEventListener("execution-completed", handler);
  }, [id, fetchTrace]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="animate-pulse text-muted-foreground">Loading trace...</div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" onClick={() => router.back()}>
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back
        </Button>
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-destructive">
          {error ?? "Not found"}
        </div>
      </div>
    );
  }

  const incident = data.incident;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" asChild>
          <Link href="/incidents">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Link>
        </Button>
      </div>

      {incident && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <CardTitle>{incident.title}</CardTitle>
              <Badge>{incident.severity}</Badge>
              <Badge variant="outline">{incident.status}</Badge>
            </div>
            {incident.metadata && (incident.metadata as { metrics_snapshot?: Record<string, unknown> }).metrics_snapshot && (
              <div className="mt-3 p-3 rounded-md bg-muted/50 font-mono text-xs">
                <p className="font-semibold mb-2">Metrics snapshot</p>
                <pre className="whitespace-pre-wrap">
                  {JSON.stringify((incident.metadata as { metrics_snapshot?: Record<string, unknown> }).metrics_snapshot, null, 2)}
                </pre>
              </div>
            )}
          </CardHeader>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_400px]">
        {/* Left: Timeline */}
        <div className="space-y-4">
          <h2 className="text-lg font-semibold">Agent Trace</h2>
          {data.trace.length === 0 ? (
            <p className="text-muted-foreground">No trace data</p>
          ) : (
            <div className="space-y-4">
              {data.trace.map((step, i) => {
                const Icon = AGENT_ICONS[step.agent_name] ?? Activity;
                let reasoning: Record<string, unknown> = {};
                try {
                  reasoning = typeof step.reasoning === "string" ? JSON.parse(step.reasoning) : {};
                } catch {
                  reasoning = { raw: step.reasoning };
                }
                return (
                  <Card key={i}>
                    <CardHeader>
                      <div className="flex items-center gap-2">
                        <Icon className="h-5 w-5 text-muted-foreground" />
                        <CardTitle className="text-base">{step.agent_name}</CardTitle>
                        <Badge variant="secondary">{step.decision_type}</Badge>
                        {step.confidence != null && (
                          <span className="text-xs text-muted-foreground">
                            {(step.confidence * 100).toFixed(0)}% conf
                          </span>
                        )}
                        {step.timestamp && (
                          <span className="text-xs text-muted-foreground ml-auto">
                            {new Date(step.timestamp).toLocaleString()}
                          </span>
                        )}
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <ExpandableSection title="Reasoning" defaultOpen={i === 0}>
                        <pre className="whitespace-pre-wrap text-xs">{JSON.stringify(reasoning, null, 2)}</pre>
                      </ExpandableSection>
                      {step.tool_calls && (step.tool_calls as unknown[]).length > 0 && (
                        <ExpandableSection title={`Tool Calls (${(step.tool_calls as unknown[]).length})`}>
                          <pre className="whitespace-pre-wrap text-xs">{JSON.stringify(step.tool_calls, null, 2)}</pre>
                        </ExpandableSection>
                      )}
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </div>

        {/* Right: Terminal */}
        <div>
          <h2 className="text-lg font-semibold mb-2">Audit Log</h2>
          <AgentTraceTerminal incidentId={id} logs={data.audit_log} />
        </div>
      </div>
    </div>
  );
}

function AgentTraceTerminal({
  incidentId,
  logs,
}: {
  incidentId: string;
  logs: AgentTraceResponse["audit_log"];
}) {
  const formatted = logs.map((a, i) => ({
    id: `audit-${i}-${a.timestamp ?? ""}`,
    incident_id: incidentId,
    agent_name: a.agent_name,
    action: a.action,
    mcp_server: a.mcp_server ?? null,
    tool_name: a.tool_name ?? null,
    input_data: {},
    output_data: {},
    timestamp: a.timestamp,
  }));
  return <AgentTerminal logs={formatted} maxHeight="400px" />;
}
