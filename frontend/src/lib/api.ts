const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${path}: ${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getStats: () => fetchApi<DashboardStats>("/api/dashboard/stats"),
  getIncidents: (status?: string) =>
    fetchApi<IncidentsResponse>(`/api/incidents${status ? `?status=${status}` : ""}`),
  getAgentTrace: (incidentId: string) =>
    fetchApi<AgentTraceResponse>(`/api/agent-trace/${incidentId}`),
  getAgentDecisions: (agentName?: string, limit?: number) => {
    const params = new URLSearchParams();
    if (agentName) params.set("agent_name", agentName);
    if (limit) params.set("limit", String(limit));
    return fetchApi<AgentDecisionsResponse>(`/api/agent-decisions${params.toString() ? `?${params}` : ""}`);
  },
  getAuditLogs: (opts?: { incidentId?: string; limit?: number; since?: string }) => {
    const params = new URLSearchParams();
    if (opts?.incidentId) params.set("incident_id", opts.incidentId);
    if (opts?.limit) params.set("limit", String(opts.limit));
    if (opts?.since) params.set("since", opts.since);
    return fetchApi<AuditLogsResponse>(`/api/audit-logs${params.toString() ? `?${params}` : ""}`);
  },
  getEvalResults: () => fetchApi<EvalResultsResponse>("/api/eval-results"),
  getEvalStatus: () => fetchApi<EvalStatusResponse>("/api/eval/status"),
  getEvalReport: () => fetchApi<EvalReportResponse>("/api/eval/report"),
  getSafetyReport: () => fetchApi<SafetyReportResponse>("/api/safety-report"),
  getServiceHealth: () => fetchApi<ServiceHealthResponse>("/api/services/health"),
  getApprovals: () => fetchApi<ApprovalsResponse>("/api/approvals"),
  getApprovalHistory: () => fetchApi<ApprovalHistoryResponse>("/api/approvals/history"),
  approve: (actionId: string, body?: { decided_by?: string; reason?: string }) =>
    fetchApi<ApproveResult>(`/api/approve/${actionId}`, {
      method: "POST",
      body: JSON.stringify(body ?? { decided_by: "human_operator" }),
    }),
  getIncidentEvents: (incidentId: string) =>
    fetchApi<IncidentEventsResponse>(`/api/incidents/${incidentId}/events`),
  reject: (actionId: string, body?: { decided_by?: string; reason?: string }) =>
    fetchApi<{ status: string }>(`/api/reject/${actionId}`, {
      method: "POST",
      body: JSON.stringify(body || { decided_by: "human_operator", reason: "Rejected by operator" }),
    }),
  injectFault: (target: string, type: string, intensity: number, duration: number) =>
    fetchApi<InjectFaultResponse>("/api/chaos/inject", {
      method: "POST",
      body: JSON.stringify({ target, type, intensity, duration }),
    }),
  stopChaos: (target: string) =>
    fetchApi<{ status: string }>("/api/chaos/stop", {
      method: "POST",
      body: JSON.stringify({ target }),
    }),
  getWatcherStatus: () => fetchApi<WatcherStatus>("/api/watcher/status"),
};

// ─── Response Types ─────────────────────────────────────────

export interface DashboardStats {
  incidents: { total: number; open: number; resolved?: number };
  agents: { total_decisions: number; total_tool_calls: number; active_agents: number };
  safety_score: number;
  eval_score: number;
  metrics?: {
    mttr_minutes: number | null;
    auto_resolve_pct: number;
    approvals_processed: number;
    approval_latency_seconds: number | null;
  };
}

export interface Incident {
  id: string;
  title: string;
  severity: string;
  status: string;
  detected_at: string | null;
  resolved_at: string | null;
  root_cause: string | null;
  metadata: Record<string, unknown>;
}

export interface IncidentsResponse {
  total: number;
  incidents: Incident[];
}

export interface AgentTraceResponse {
  incident: Incident | null;
  trace: Array<{
    agent_name: string;
    decision_type: string;
    reasoning: string;
    confidence: number | null;
    tool_calls: unknown[];
    timestamp: string | null;
  }>;
  audit_log: Array<{
    agent_name: string;
    action: string;
    mcp_server: string | null;
    tool_name: string | null;
    timestamp: string | null;
  }>;
  timeline?: Array<{
    timestamp: string;
    type: "decision" | "audit" | "event";
    data: Record<string, unknown>;
  }>;
}

export interface AgentDecision {
  id: string;
  incident_id: string | null;
  agent_name: string;
  decision_type: string;
  reasoning: string;
  confidence: number | null;
  tool_calls: unknown[];
  created_at: string | null;
}

export interface AgentDecisionsResponse {
  total: number;
  decisions: AgentDecision[];
}

export interface AuditLogEntry {
  id: string;
  incident_id: string | null;
  agent_name: string;
  action: string;
  mcp_server: string | null;
  tool_name: string | null;
  input_data: Record<string, unknown>;
  output_data: Record<string, unknown>;
  timestamp: string | null;
}

export interface AuditLogsResponse {
  total: number;
  logs: AuditLogEntry[];
}

export interface EvalResultsResponse {
  total: number;
  evaluations: Array<{
    timestamp?: string;
    model?: string;
    results?: Record<
      string,
      { scores?: Record<string, number>; watcher_alert?: boolean; diagnosis_root_cause?: string }
    >;
  }>;
}

export interface EvalScenarioResult {
  scenario: string;
  target: string;
  score: number;
  detection_time_s: number | null;
  diagnosis_time_s: number | null;
  resolution_time_s: number | null;
  root_cause_found: string | null;
  root_cause_correct: boolean;
  resolution_status: string | null;
  tool_count: number;
  approval_count: number;
  errors: string[];
}

export interface EvalStatusResponse {
  has_results: boolean;
  message?: string;
  error?: string;
  timestamp?: string;
  scenarios_run?: number;
  overall_score?: number;
  model?: string;
  scenarios?: EvalScenarioResult[];
}

export interface EvalReportResponse {
  has_report: boolean;
  message?: string;
  error?: string;
  timestamp?: string;
  content?: string;
}

export interface SafetyReportResponse {
  error?: string;
  composite_safety_score?: number;
  deployment_allowed?: boolean;
  threshold?: number;
  category_scores?: Record<string, number>;
  guardrails?: {
    guardrails: Record<string, { status: string; description: string; evidence?: string }>;
    active: number;
    total: number;
    score: number;
  };
}

export interface ServiceHealth {
  name: string;
  cpu_percent: number;
  memory_percent: number;
  response_time_ms: number;
  error_rate: number;
  status: string;
}

export interface ServiceHealthResponse {
  services: ServiceHealth[];
}

export interface ApprovalRequest {
  id: string;
  incident_id?: string;
  agent_name: string;
  action: string;
  tool: string;
  tool_args: Record<string, unknown>;
  risk_level: string;
  service: string;
  status: string;
  requested_at: string;
  decided_at?: string | null;
  decided_by?: string | null;
  reason?: string | null;
}

export interface ApprovalsResponse {
  total_pending: number;
  approvals: ApprovalRequest[];
}

export interface ApprovalHistoryResponse {
  total: number;
  pending: number;
  approved: number;
  rejected: number;
  history: ApprovalRequest[];
}

export interface ApproveResult {
  status: string;
  action_id?: string;
  action?: string;
  tool?: string;
  risk_level?: string;
  decided_by?: string;
  message?: string;
  execution_result?: {
    status: string;
    result?: Record<string, unknown>;
  };
  incident_resolved?: boolean;
  incident_id?: string;
}

export interface InjectFaultResponse {
  status: string;
  fault: string;
  target: string;
  duration: number;
}

export interface WatcherStatus {
  enabled: boolean;
  poll_interval_seconds: number;
  services_monitored: string[];
  last_check: string | null;
  anomaly_streaks: Record<string, number>;
}

export interface IncidentEventsResponse {
  incident_id: string;
  events: Array<{
    id: string;
    event_type: string;
    payload: Record<string, unknown>;
    created_at: string | null;
  }>;
}
