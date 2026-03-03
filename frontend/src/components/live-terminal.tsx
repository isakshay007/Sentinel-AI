"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { api, type AgentDecision, type AuditLogEntry } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Pause, Play, Trash2 } from "lucide-react";

interface LogLine {
  id: string;
  time: string;
  agent: string;
  message: string;
  level: "info" | "warning" | "error" | "agent" | "system";
}

const LEVEL_COLORS: Record<LogLine["level"], string> = {
  info: "text-emerald-400",
  warning: "text-yellow-400",
  error: "text-red-400",
  agent: "text-cyan-400",
  system: "text-blue-400",
};

const AGENT_LABELS: Record<string, string> = {
  watcher: "WATCHER",
  diagnostician: "DIAGNOSTICIAN",
  strategist: "STRATEGIST",
  executor: "EXECUTOR",
  chaos_injector: "CHAOS",
};

function formatTime(iso: string | null | undefined): string {
  if (!iso) return "--:--:--";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "--:--:--";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  } catch {
    return "--:--:--";
  }
}

function classifyLevel(agentName: string, decisionType?: string): LogLine["level"] {
  if (agentName === "chaos_injector") return "warning";
  if (agentName === "executor") return "error";
  if (agentName === "system") return "system";
  if (decisionType === "detect" || decisionType === "anomaly_detected") return "warning";
  return "agent";
}

function decisionToLog(d: AgentDecision): LogLine {
  const label = AGENT_LABELS[d.agent_name] ?? d.agent_name?.toUpperCase() ?? "UNKNOWN";
  let msg = d.decision_type ?? "action";
  try {
    const parsed = JSON.parse(d.reasoning ?? "{}");
    if (parsed?.summary) msg = parsed.summary;
    else if (parsed?.root_cause) msg = `Root cause: ${parsed.root_cause}`;
  } catch { /* use decision_type */ }

  return {
    id: `d-${d.id}`,
    time: formatTime(d.created_at),
    agent: label,
    message: typeof msg === "string" ? msg.slice(0, 120) : String(msg),
    level: classifyLevel(d.agent_name, d.decision_type),
  };
}

function auditToLog(a: AuditLogEntry): LogLine {
  const label = AGENT_LABELS[a.agent_name] ?? a.agent_name?.toUpperCase() ?? "SYSTEM";
  const tool = a.tool_name ?? a.action ?? "action";
  const server = a.mcp_server ? ` (${a.mcp_server})` : "";
  return {
    id: `a-${a.id}`,
    time: formatTime(a.timestamp),
    agent: label,
    message: `${tool}${server}`,
    level: a.agent_name === "chaos_injector" ? "warning" : "system",
  };
}

export function LiveTerminal() {
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [paused, setPaused] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const seenIds = useRef(new Set<string>());

  const fetchLogs = useCallback(async () => {
    if (paused) return;
    try {
      const [decRes, auditRes] = await Promise.all([
        api.getAgentDecisions(undefined, 20).catch(() => ({ decisions: [] as AgentDecision[], total: 0 })),
        api.getAuditLogs({ limit: 20 }).catch(() => ({ logs: [] as AuditLogEntry[], total: 0 })),
      ]);

      const newLines: LogLine[] = [];
      for (const d of decRes.decisions ?? []) {
        const line = decisionToLog(d);
        if (!seenIds.current.has(line.id)) {
          seenIds.current.add(line.id);
          newLines.push(line);
        }
      }
      for (const a of auditRes.logs ?? []) {
        const line = auditToLog(a);
        if (!seenIds.current.has(line.id)) {
          seenIds.current.add(line.id);
          newLines.push(line);
        }
      }

      if (newLines.length > 0) {
        setLogs((prev) => {
          const combined = [...prev, ...newLines];
          combined.sort((a, b) => a.time.localeCompare(b.time));
          return combined.slice(-80);
        });
      }
    } catch { /* silently retry next interval */ }
  }, [paused]);

  useEffect(() => {
    fetchLogs();
    const id = setInterval(fetchLogs, 3000);
    return () => clearInterval(id);
  }, [fetchLogs]);

  useEffect(() => {
    if (!paused && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, paused]);

  const handleClear = () => {
    setLogs([]);
    seenIds.current.clear();
  };

  return (
    <div className="flex flex-col rounded-xl overflow-hidden border border-slate-700/30 shadow-xl shadow-black/20 h-full">
      {/* Mac-style title bar */}
      <div className="flex items-center h-9 px-3.5 bg-[#1c1c1e] border-b border-slate-800/60 shrink-0">
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-[#ff5f57]" />
          <span className="w-2.5 h-2.5 rounded-full bg-[#febc2e]" />
          <span className="w-2.5 h-2.5 rounded-full bg-[#28c840]" />
        </div>
        <span className="flex-1 text-center text-[10px] font-medium text-slate-500 tracking-wide">
          SentinelAI Live System Logs
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setPaused(!paused)}
            className="p-1 rounded hover:bg-white/5 transition-smooth text-slate-500 hover:text-slate-300"
          >
            {paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
          </button>
          <button
            onClick={handleClear}
            className="p-1 rounded hover:bg-white/5 transition-smooth text-slate-500 hover:text-slate-300"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* Terminal body */}
      <div
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-y-auto bg-[#0b0f14] px-3.5 py-2.5 font-mono text-[11px] leading-[1.7] terminal-scrollbar"
      >
        {logs.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-slate-700 text-[11px]">Waiting for agent activity...</p>
          </div>
        ) : (
          logs.map((line) => (
            <div key={line.id} className="animate-terminal-line flex gap-1.5">
              <span className="text-slate-600 shrink-0">[{line.time}]</span>
              <span className={cn("font-semibold shrink-0", LEVEL_COLORS[line.level])}>
                {line.agent}
              </span>
              <span className="text-slate-600 shrink-0">&rarr;</span>
              <span className="text-slate-400 terminal-glow">{line.message}</span>
            </div>
          ))
        )}
        {paused && (
          <div className="text-yellow-500/60 text-[10px] mt-2 animate-status-pulse">
            ⏸ Paused — click play to resume
          </div>
        )}
      </div>
    </div>
  );
}
