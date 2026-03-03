"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  AlertTriangle,
  CheckSquare,
  ExternalLink,
  Shield,
  Brain,
  Swords,
  Zap,
  Eye,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, type AgentDecision, type WatcherStatus } from "@/lib/api";

const NAV_ITEMS = [
  { href: "/", icon: LayoutDashboard, label: "Dashboard" },
  { href: "/incidents", icon: AlertTriangle, label: "Incidents", badgeKey: "incidents" as const },
  { href: "/approvals", icon: CheckSquare, label: "Approvals", badgeKey: "approvals" as const },
];

const EXTERNAL_LINKS = [
  { href: "http://localhost:3001", label: "Grafana", icon: ExternalLink },
  { href: "http://localhost:9090", label: "Prometheus", icon: ExternalLink },
];

const AGENT_META: Record<string, { label: string; color: string; icon: React.ElementType; bgColor: string; borderColor: string }> = {
  watcher: { label: "Watcher", color: "#3b82f6", icon: Eye, bgColor: "bg-blue-600", borderColor: "border-blue-400/50" },
  diagnostician: { label: "Diagnostician", color: "#eab308", icon: Brain, bgColor: "bg-yellow-500", borderColor: "border-yellow-400/50" },
  strategist: { label: "Strategist", color: "#f97316", icon: Swords, bgColor: "bg-orange-500", borderColor: "border-orange-400/50" },
  executor: { label: "Executor", color: "#ef4444", icon: Zap, bgColor: "bg-red-600", borderColor: "border-red-400/50" },
};

type AgentState = "idle" | "monitoring" | "investigating" | "acting";

function getAgentState(agentName: string, decisions: AgentDecision[], watcherStatus: WatcherStatus | null): AgentState {
  // Watcher: always-on, derive from watcher status
  if (agentName === "watcher" && watcherStatus?.enabled) {
    const hasStreak = Object.values(watcherStatus.anomaly_streaks || {}).some((s) => s > 0);
    return hasStreak ? "investigating" : "monitoring";
  }

  // For other agents: look at recent decisions to determine pipeline stage
  const now = Date.now();

  // Find the most recent decision per agent type
  const latestByAgent: Record<string, AgentDecision> = {};
  for (const d of decisions) {
    if (!d.agent_name || !d.created_at) continue;
    if (!latestByAgent[d.agent_name] || new Date(d.created_at) > new Date(latestByAgent[d.agent_name].created_at ?? "")) {
      latestByAgent[d.agent_name] = d;
    }
  }

  // Pipeline order: watcher → diagnostician → strategist → executor
  const pipelineOrder = ["watcher", "diagnostician", "strategist", "executor"];
  const agentIdx = pipelineOrder.indexOf(agentName);

  // Check if this agent has a recent decision
  const myDecision = latestByAgent[agentName];
  const myAgeMs = myDecision ? now - new Date(myDecision.created_at ?? "").getTime() : Infinity;

  // Recent decision thresholds (wider to match real pipeline times)
  if (myAgeMs < 60_000) return "acting";      // Produced output within last 60s
  if (myAgeMs < 300_000) return "investigating"; // Active within last 5min

  // Pipeline inference: if the agent BEFORE us in the pipeline recently acted,
  // we should show as "investigating" (we're likely working or about to work)
  if (agentIdx > 0) {
    const prevAgent = pipelineOrder[agentIdx - 1];
    const prevDecision = latestByAgent[prevAgent];
    if (prevDecision?.created_at) {
      const prevAge = now - new Date(prevDecision.created_at).getTime();
      // If the previous agent acted recently AND we haven't produced output yet (or our output is older),
      // we're likely in-progress
      if (prevAge < 120_000 && (myAgeMs > prevAge)) {
        return "investigating";
      }
    }
  }

  return "idle";
}

const STATE_CONFIG: Record<AgentState, { label: string; dotClass: string }> = {
  idle: { label: "Idle", dotClass: "bg-slate-600" },
  monitoring: { label: "Monitoring", dotClass: "bg-green-500 animate-status-pulse" },
  investigating: { label: "Investigating", dotClass: "bg-yellow-500 animate-status-pulse" },
  acting: { label: "Acting", dotClass: "bg-red-500 animate-status-pulse" },
};

export function Sidebar() {
  const pathname = usePathname();
  const [counts, setCounts] = useState({ incidents: 0, approvals: 0 });
  const [decisions, setDecisions] = useState<AgentDecision[]>([]);
  const [watcherStatus, setWatcherStatus] = useState<WatcherStatus | null>(null);

  const refresh = useCallback(() => {
    api.getIncidents("open").then((r) => setCounts((c) => ({ ...c, incidents: r?.total ?? 0 }))).catch(() => { });
    api.getApprovals().then((r) => setCounts((c) => ({ ...c, approvals: r?.total_pending ?? 0 }))).catch(() => { });
    api.getAgentDecisions(undefined, 10).then((r) => setDecisions(r?.decisions ?? [])).catch(() => { });
    api.getWatcherStatus().then(setWatcherStatus).catch(() => { });
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 3000);
    const handler = () => refresh();
    window.addEventListener("approvals-updated", handler);
    window.addEventListener("execution-completed", handler);
    return () => {
      clearInterval(id);
      window.removeEventListener("approvals-updated", handler);
      window.removeEventListener("execution-completed", handler);
    };
  }, [refresh]);

  return (
    <aside className="w-[230px] shrink-0 border-r border-slate-800/40 bg-[#070b16]/70 backdrop-blur-xl flex flex-col fixed inset-y-0 left-0 z-40 overflow-hidden">
      {/* Logo */}
      <div className="px-5 h-16 flex items-center gap-3 relative">
        <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-blue-500/20 to-transparent" />
        <div className="w-9 h-9 rounded-lg bg-blue-500/10 flex items-center justify-center border border-blue-500/20 shadow-[0_0_15px_rgba(59,130,246,0.2)] animate-logo-breathe group/logo">
          <Shield className="h-5 w-5 text-blue-400 group-hover/logo:scale-110 transition-transform duration-500" />
        </div>
        <div className="flex flex-col">
          <span className="text-[13px] font-black uppercase tracking-[0.35em] text-white">
            Sentinel AI
          </span>
        </div>
      </div>

      <Separator className="bg-border/30" />

      {/* Navigation */}
      <nav className="px-3 py-3 space-y-0.5">
        {NAV_ITEMS.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));
          const count = item.badgeKey ? counts[item.badgeKey] : 0;
          return (
            <Link key={item.href} href={item.href} className="group/nav relative">
              <div
                className={cn(
                  "flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] font-medium transition-all duration-300 relative overflow-hidden",
                  isActive
                    ? "text-blue-400 group-hover/nav:bg-blue-500/5"
                    : "text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]"
                )}
              >
                {isActive && (
                  <>
                    <div className="absolute left-0 top-1.5 bottom-1.5 w-[2px] bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.8)] rounded-full animate-fade-in" />
                    <div className="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent animate-fade-in" />
                  </>
                )}
                <item.icon className={cn("h-3.5 w-3.5 shrink-0 transition-transform duration-300 group-hover/nav:scale-110", isActive && "drop-shadow-[0_0_4px_rgba(59,130,246,0.6)]")} />
                <span className="flex-1 uppercase tracking-[0.12em] font-bold text-[11px] leading-none">{item.label}</span>
                {count > 0 && (
                  <Badge
                    variant="destructive"
                    className="h-[18px] min-w-[18px] px-1 text-[10px] font-bold justify-center rounded-full badge-update shadow-[0_0_10px_rgba(239,68,68,0.3)] animate-pulse"
                  >
                    {count}
                  </Badge>
                )}
              </div>
            </Link>
          );
        })}
      </nav>

      <Separator className="mx-3 bg-border/30" />

      {/* Agent Status Section */}
      <div className="px-3 py-3">
        <p className="px-3 text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">
          Agent Status
        </p>
        <div className="space-y-0.5">
          {Object.entries(AGENT_META).map(([key, meta]) => {
            const state = getAgentState(key, decisions, watcherStatus);
            const cfg = STATE_CONFIG[state];
            const Icon = meta.icon;
            const isActive = state !== "idle";
            return (
              <Tooltip key={key}>
                <TooltipTrigger asChild>
                  <div className={cn(
                    "flex items-center gap-2.5 px-3 py-2 rounded-md text-[12px] transition-smooth group",
                    isActive ? "bg-white/[0.04]" : "hover:bg-white/[0.02]"
                  )}>
                    <div
                      className={cn(
                        "w-5 h-5 rounded flex items-center justify-center transition-all duration-300",
                        isActive ? meta.bgColor : "bg-slate-800/30",
                        isActive && "shadow-[0_0_8px_rgba(0,0,0,0.3)]"
                      )}
                    >
                      <Icon
                        className={cn("h-3 w-3", isActive ? "text-white" : "text-slate-500")}
                      />
                    </div>
                    <span className={cn("flex-1 uppercase tracking-[0.12em] font-bold text-[10px] leading-none", isActive ? "text-slate-200" : "text-slate-500")}>
                      {meta.label}
                    </span>
                    <span className="relative flex h-2.5 w-2.5 shrink-0">
                      {isActive && (
                        <span
                          className={cn("absolute inset-0 rounded-full opacity-50", cfg.dotClass)}
                          style={{ animation: "status-pulse 2s ease-in-out infinite" }}
                        />
                      )}
                      <span className={cn("relative inline-flex rounded-full h-2.5 w-2.5", cfg.dotClass)} />
                    </span>
                  </div>
                </TooltipTrigger>
                <TooltipContent side="right" className="text-xs">
                  <p>{meta.label}: <span className="font-semibold">{cfg.label}</span></p>
                </TooltipContent>
              </Tooltip>
            );
          })}
        </div>
      </div>

      {/* Spacer to push external links to bottom */}
      <div className="flex-1" />

      <Separator className="mx-3 bg-border/30" />

      {/* External links */}
      <div className="px-3 pt-3 pb-8 space-y-0.5 relative">
        <div className="absolute inset-0 bg-gradient-to-t from-black/20 to-transparent pointer-events-none" />
        <p className="px-3 text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5 relative z-10">
          External
        </p>
        {EXTERNAL_LINKS.map((link) => (
          <a
            key={link.href}
            href={link.href}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2.5 px-3 py-1.5 rounded-md text-[12px] text-slate-500 hover:text-blue-400 hover:bg-blue-500/5 transition-all duration-300 relative z-10 group/link"
          >
            <link.icon className="h-3 w-3 shrink-0 opacity-50 group-hover/link:opacity-100 transition-opacity" />
            <span className="uppercase tracking-[0.1em] font-bold text-[10px]">{link.label}</span>
          </a>
        ))}
      </div>
    </aside>
  );
}
