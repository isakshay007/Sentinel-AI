"use client";

import { useRef, useEffect, useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import type { TerminalWindowState } from "@/contexts/terminal-windows-context";
import { useTerminalWindows } from "@/contexts/terminal-windows-context";
import { api } from "@/lib/api";
import type { AuditLogEntry } from "@/lib/api";

const TITLE_BAR_H = 28;

export function TerminalWindow({ window: win }: { window: TerminalWindowState }) {
  const {
    closeTerminal,
    focusTerminal,
    updateTerminal,
    toggleMinimize,
    toggleMaximize,
  } = useTerminalWindows();

  const containerRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, posX: 0, posY: 0 });
  const resizeStart = useRef({ x: 0, y: 0, w: 0, h: 0, posX: 0, posY: 0, dir: "" });

  const handleTitleMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest("button")) return;
    setIsDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY, posX: win.position.x, posY: win.position.y };
  };

  const handleResizeMouseDown = (e: React.MouseEvent, dir: string) => {
    e.stopPropagation();
    setIsResizing(true);
    resizeStart.current = {
      x: e.clientX,
      y: e.clientY,
      w: win.size.width,
      h: win.size.height,
      posX: win.position.x,
      posY: win.position.y,
      dir,
    };
  };

  useEffect(() => {
    if (!isDragging) return;
    const onMove = (e: MouseEvent) => {
      const dx = e.clientX - dragStart.current.x;
      const dy = e.clientY - dragStart.current.y;
      updateTerminal(win.id, {
        position: { x: dragStart.current.posX + dx, y: dragStart.current.posY + dy },
      });
    };
    const onUp = () => setIsDragging(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [isDragging, win.id, updateTerminal]);

  useEffect(() => {
    if (!isResizing) return;
    const start = resizeStart.current;
    const onMove = (e: MouseEvent) => {
      const { x, y, w, h, posX, posY, dir } = start;
      let nw = w;
      let nh = h;
      let nx = posX;
      let ny = posY;
      if (dir.includes("e")) nw = Math.max(320, w + (e.clientX - x));
      if (dir.includes("w")) {
        const dw = e.clientX - x;
        nw = Math.max(320, w - dw);
        nx = posX + dw;
      }
      if (dir.includes("s")) nh = Math.max(200, h + (e.clientY - y));
      if (dir.includes("n")) {
        const dh = e.clientY - y;
        nh = Math.max(200, h + dh);
        ny = posY + dh;
      }
      updateTerminal(win.id, {
        size: { width: nw, height: nh },
        position: { x: nx, y: ny },
      });
    };
    const onUp = () => setIsResizing(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [isResizing, win.id, updateTerminal]);

  const mainRect = typeof document !== "undefined" ? document.querySelector("main")?.getBoundingClientRect() : null;

  const style: React.CSSProperties = win.maximized && mainRect
    ? {
        position: "fixed",
        left: mainRect.left,
        top: mainRect.top,
        width: mainRect.width,
        height: mainRect.height,
        zIndex: win.zIndex,
      }
    : {
        position: "fixed",
        left: win.position.x,
        top: win.position.y,
        width: win.size.width,
        height: win.minimized ? TITLE_BAR_H : win.size.height,
        zIndex: win.zIndex,
      };

  return (
    <div
      ref={containerRef}
      className="rounded-lg overflow-hidden shadow-2xl border border-[#2d2d2d] flex flex-col bg-[#1E1E1E] select-none relative"
      style={style}
      onClick={() => focusTerminal(win.id)}
    >
      {/* Title bar - macOS style */}
      <div
        className="flex items-center h-7 px-2 bg-[#3C3C3C] gap-2 shrink-0 cursor-move"
        onMouseDown={handleTitleMouseDown}
        style={{ minHeight: TITLE_BAR_H }}
      >
        <div className="flex gap-1.5 shrink-0">
          {/* macOS-style traffic light buttons with hover glyphs */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              closeTerminal(win.id);
            }}
            className="group w-3 h-3 rounded-full bg-[#FF5F56] hover:bg-[#FF5F56]/90 transition-colors flex items-center justify-center"
            title="Close"
            aria-label="Close terminal"
          >
            <span className="text-[8px] leading-none text-white opacity-0 group-hover:opacity-100">
              ×
            </span>
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              toggleMinimize(win.id);
            }}
            className="group w-3 h-3 rounded-full bg-[#FFBD2E] hover:bg-[#FFBD2E]/90 transition-colors flex items-center justify-center"
            title="Minimize"
            aria-label="Minimize"
          >
            <span className="text-[10px] leading-none text-white opacity-0 group-hover:opacity-100">
              –
            </span>
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              toggleMaximize(win.id);
            }}
            className="group w-3 h-3 rounded-full bg-[#27C93F] hover:bg-[#27C93F]/90 transition-colors flex items-center justify-center"
            title="Maximize"
            aria-label="Maximize"
          >
            <span className="text-[8px] leading-none text-white opacity-0 group-hover:opacity-100">
              ⤢
            </span>
          </button>
        </div>
        <span className="text-xs text-gray-400 mx-auto pointer-events-none font-medium">
          {win.title}
        </span>
      </div>

      {!win.minimized && (
        <>
          <div className="terminal-body flex-1 min-h-0 overflow-hidden flex flex-col">
            <TerminalBody window={win} />
          </div>

          {/* Resize handles - only when not maximized */}
          {!win.maximized && (
            <>
              <div className="absolute bottom-0 left-0 right-0 h-[6px] cursor-ns-resize z-10" onMouseDown={(e) => handleResizeMouseDown(e, "s")} />
              <div className="absolute top-7 right-0 bottom-0 w-[6px] cursor-ew-resize z-10" onMouseDown={(e) => handleResizeMouseDown(e, "e")} />
              <div className="absolute top-7 left-0 bottom-0 w-[6px] cursor-ew-resize z-10" onMouseDown={(e) => handleResizeMouseDown(e, "w")} />
              <div className="absolute top-7 left-0 right-0 h-[6px] cursor-ns-resize z-10" onMouseDown={(e) => handleResizeMouseDown(e, "n")} />
              <div className="absolute bottom-0 right-0 w-[12px] h-[12px] cursor-nwse-resize z-10" onMouseDown={(e) => handleResizeMouseDown(e, "se")} />
              <div className="absolute bottom-0 left-0 w-[12px] h-[12px] cursor-nesw-resize z-10" onMouseDown={(e) => handleResizeMouseDown(e, "sw")} />
              <div className="absolute top-7 right-0 w-[12px] h-[12px] cursor-nesw-resize z-10" onMouseDown={(e) => handleResizeMouseDown(e, "ne")} />
              <div className="absolute top-0 left-0 w-[12px] h-[12px] cursor-nwse-resize z-10" onMouseDown={(e) => handleResizeMouseDown(e, "nw")} />
            </>
          )}
        </>
      )}
    </div>
  );
}

function TerminalBody({ window: win }: { window: TerminalWindowState }) {
  if (win.type === "pipeline") return <PipelineTerminalBody window={win} />;
  if (win.type === "agent") return <AgentTerminalBody window={win} />;
  if (win.type === "activity") return <ActivityTerminalBody window={win} />;
  return null;
}

function PipelineTerminalBody({ window: win }: { window: TerminalWindowState }) {
  const { appendPipelineLine } = useTerminalWindows();
  const bottomRef = useRef<HTMLDivElement>(null);
  const completedShown = useRef(false);

  const pipeline = win.pipeline!;
  const startedAt = pipeline.startedAt;

  // Poll audit logs and append new lines
  useEffect(() => {
    if (!startedAt || !win.visible) return;
    const sinceIso = new Date(startedAt).toISOString();
    const seenIds = new Set<string>();

    const poll = async () => {
      try {
        const res = await api.getAuditLogs({ since: sinceIso, limit: 100 });
        const logs = (res.logs || []).filter((l) => !seenIds.has(l.id)).reverse();
        for (const log of logs) {
          seenIds.add(log.id);
          const ts = log.timestamp
            ? new Date(log.timestamp).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
            : "--:--:--";
          if (log.action === "mcp_tool_call" && log.tool_name) {
            const args = log.input_data ? JSON.stringify(log.input_data).slice(0, 50) : "";
            appendPipelineLine(win.id, `[${ts}] 🔧 ${log.agent_name} → ${log.tool_name}(${args}${args ? "…" : ""})`);
            const summary = (log.output_data as { summary?: string })?.summary;
            if (summary) appendPipelineLine(win.id, `[${ts}] ✓ ${summary}`);
          } else {
            appendPipelineLine(win.id, `[${ts}] ▶ ${log.agent_name} — ${log.action}`);
          }
        }
      } catch {
        /* ignore */
      }
    };

    poll();
    const id = setInterval(poll, 10000); // 10s poll (reduced during debugging)
    return () => clearInterval(id);
  }, [startedAt, win.id, win.visible, appendPipelineLine]);

  // When pipeline result arrives, append final summary
  useEffect(() => {
    if (pipeline.result && !completedShown.current) {
      completedShown.current = true;
      const r = pipeline.result as { incident_id?: string; pending_approvals?: number; error?: string };
      if (r.error) {
        appendPipelineLine(win.id, `✗ Pipeline failed: ${r.error}`);
      } else {
        appendPipelineLine(win.id, "");
        appendPipelineLine(win.id, `[${new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}] ✓ Pipeline complete. Incident created.`);
        if (r.incident_id) appendPipelineLine(win.id, `[${new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}] 📋 New incident: ${r.incident_id.slice(0, 8)}…`);
        if (r.pending_approvals && r.pending_approvals > 0) appendPipelineLine(win.id, `[${new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}] ⏳ ${r.pending_approvals} action(s) awaiting human approval`);
        appendPipelineLine(win.id, "");
        appendPipelineLine(win.id, "akshay@sentinelai ~ % _");
      }
    }
  }, [pipeline.result, win.id, appendPipelineLine]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [pipeline.lines.length]);

  return (
    <div className="p-4 font-mono text-[13px] leading-relaxed overflow-y-auto flex-1 min-h-0 bg-[#1E1E1E]">
      <div className="space-y-0.5">
        {pipeline.lines.map((line, i) => (
          <div key={i} className="flex">
            {line.startsWith("[") ? (
              <>
                <span className="text-[#6A9955] shrink-0">{line.match(/^\[[^\]]+\]/)?.[0] ?? ""} </span>
                <span className={cn(
                  line.includes("✓") && "text-[#27C93F]",
                  line.includes("✗") && "text-[#FF5F56]",
                  line.includes("🔧") && "text-[#4EC9B0]",
                  line.includes("▶") && "text-[#DCDCAA]",
                  !line.includes("✓") && !line.includes("✗") && !line.includes("🔧") && !line.includes("▶") && "text-[#D4D4D4]"
                )}>{line.replace(/^\[[^\]]+\]\s*/, "")}</span>
              </>
            ) : (
              <span className={cn(
                line.startsWith("akshay@") && "text-[#27C93F]",
                line.startsWith("run-pipeline") && "text-[#569CD6]",
                !line.startsWith("akshay@") && !line.startsWith("run-pipeline") && "text-[#D4D4D4]"
              )}>{line || " "}</span>
            )}
          </div>
        ))}
        {!pipeline.lines.some((l) => l.startsWith("akshay@") && l.includes("%")) && (
          <div className="text-[#27C93F]">
            <span className="inline-block w-2 h-4 bg-white animate-pulse ml-1 align-middle" />
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function AgentTerminalBody({ window: win }: { window: TerminalWindowState }) {
  const { setAgentDecisions } = useTerminalWindows();
  const bottomRef = useRef<HTMLDivElement>(null);
  const agent = win.agent!;

  const fetchDecisions = useCallback(() => {
    if (!agent.agentId) return;
    api.getAgentDecisions(agent.agentId, 5).then((r) => setAgentDecisions(win.id, r.decisions)).catch(() => {});
  }, [agent.agentId, win.id, setAgentDecisions]);

  useEffect(() => {
    if (!win.visible || !agent.agentId) return;
    fetchDecisions();
  }, [win.visible, agent.agentId, fetchDecisions]);

  useEffect(() => {
    const handler = () => fetchDecisions();
    window.addEventListener("scenario-completed", handler);
    window.addEventListener("execution-completed", handler);
    const id = win.visible ? setInterval(fetchDecisions, 10000) : undefined;
    return () => {
      window.removeEventListener("scenario-completed", handler);
      window.removeEventListener("execution-completed", handler);
      if (id) clearInterval(id);
    };
  }, [fetchDecisions, win.visible]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [agent.decisions.length]);

  const formatReasoning = (r: string | null) => {
    if (!r) return "—";
    const toStr = (v: unknown): string => {
      if (v == null) return "";
      if (typeof v === "string") return v;
      if (Array.isArray(v)) {
        const first = v[0];
        if (typeof first === "string") return first;
        if (first && typeof first === "object") return toStr((first as { step?: string; hypothesis?: string }).hypothesis ?? (first as { root_cause?: string }).root_cause ?? first);
        return "";
      }
      if (typeof v === "object") return "";
      return String(v);
    };
    try {
      const o = JSON.parse(r) as Record<string, unknown>;
      const s =
        toStr(o.summary) ||
        toStr(o.root_cause) ||
        toStr(o.diagnosis) ||
        toStr(o.hypothesis) ||
        toStr(o.selected_plan) ||
        toStr(o.evidence_summary) ||
        (Array.isArray(o.analysis) ? toStr(o.analysis[0]) : toStr(o.analysis)) ||
        (Array.isArray(o.reasoning_chain) ? toStr((o.reasoning_chain[0] as { hypothesis?: string })?.hypothesis ?? (o.reasoning_chain[0] as { step?: string })?.step) : "");
      if (s) return s.slice(0, 120) + (s.length > 120 ? "…" : "");
      return JSON.stringify(o).slice(0, 80) + "…";
    } catch {
      return String(r).slice(0, 80) + "…";
    }
  };

  const getToolIcon = (tool: string | undefined) => {
    if (!tool) return "🔧";
    const t = tool.toLowerCase();
    if (t.includes("create_incident_ticket") || t === "create_incident_ticket") return "📋";
    if (t.includes("send_notification") || t === "send_notification") return "📢";
    return "🔧";
  };

  const decisions = agent.decisions as Array<{ id: string; decision_type: string; confidence: number | null; reasoning: string | null; created_at: string | null; tool_calls: unknown[] }>;

  return (
    <div className="p-4 font-mono text-[13px] leading-relaxed overflow-y-auto flex-1 min-h-0 bg-[#1E1E1E]">
      <div className="space-y-0.5 text-[#D4D4D4]">
        <div className="text-[#27C93F]">akshay@sentinelai ~ % agent-log {agent.agentId}</div>
        <div className="text-[#6A9955]"></div>
        {decisions.length === 0 ? (
          <div className="text-[#6A9955]">No decisions yet</div>
        ) : (
          decisions.map((d, i) => {
            const ago = d.created_at ? formatTimeAgo(d.created_at) : "";
            return (
              <div key={d.id} className="space-y-1 py-2">
                <div className="text-[#569CD6]">── Decision #{i + 1} ({ago}) ──────────────────</div>
                <div className="text-[#DCDCAA]">Type: {d.decision_type} | Confidence: {d.confidence != null ? `${(d.confidence * 100).toFixed(0)}%` : "—"}</div>
                <div className="text-[#D4D4D4]">Summary: {formatReasoning(d.reasoning)}</div>
                {Array.isArray(d.tool_calls) && d.tool_calls.length > 0 && (
                  <div className="text-[#4EC9B0] pl-2">
                    Tools called: {d.tool_calls.length}
                    {(d.tool_calls as Array<{ tool?: string; result_summary?: string }>).slice(0, 6).map((tc, j) => (
                      <div key={j} className="text-[13px]">  {getToolIcon(tc.tool)} {tc.tool ?? "?"} → {(tc.result_summary ?? "").slice(0, 40)}</div>
                    ))}
                  </div>
                )}
              </div>
            );
          })
        )}
        <div className="text-[#27C93F] mt-2">akshay@sentinelai ~ % <span className="inline-block w-2 h-4 bg-white animate-pulse ml-1 align-middle" /></div>
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function ActivityTerminalBody({ window: win }: { window: TerminalWindowState }) {
  const { setActivityLogs } = useTerminalWindows();
  const bottomRef = useRef<HTMLDivElement>(null);
  const activity = win.activity!;

  useEffect(() => {
    if (!win.visible) return;
    api.getAuditLogs({ limit: 100 }).then((r) => setActivityLogs(win.id, r.logs)).catch(() => {});
  }, [win.visible, win.id, setActivityLogs]);

  useEffect(() => {
    const refresh = () => api.getAuditLogs({ limit: 100 }).then((r) => setActivityLogs(win.id, r.logs)).catch(() => {});
    const handler = () => refresh();
    window.addEventListener("scenario-completed", handler);
    window.addEventListener("execution-completed", handler);
    refresh(); // initial fetch when listener mounts
    const id = setInterval(refresh, 10000); // 10s poll (reduced during debugging)
    return () => {
      window.removeEventListener("scenario-completed", handler);
      window.removeEventListener("execution-completed", handler);
      clearInterval(id);
    };
  }, [win.id, setActivityLogs]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activity.logs.length]);

  const logs = activity.logs as AuditLogEntry[];

  return (
    <div className="p-4 font-mono text-[13px] leading-relaxed overflow-y-auto flex-1 min-h-0 bg-[#1E1E1E]">
      <div className="space-y-0.5">
        <div className="text-[#27C93F]">akshay@sentinelai ~ % tail -f audit.log</div>
        <div className="text-[#6A9955]"></div>
        {logs.length === 0 ? (
          <div className="text-[#6A9955]">No recent activity</div>
        ) : (
          [...logs].reverse().map((log) => {
            const ts = log.timestamp ? new Date(log.timestamp).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--:--:--";
            const isToolCall = log.action === "mcp_tool_call";
            return (
              <div key={log.id} className="text-[#D4D4D4]">
                <span className="text-[#6A9955]">[{ts}]</span>
                <span className="text-[#DCDCAA]"> {isToolCall ? "🔧" : "▶"} </span>
                <span className="text-[#DCDCAA]">{log.agent_name}</span>
                {isToolCall && log.tool_name ? (
                  <span> → <span className="text-[#4EC9B0]">{log.tool_name}</span></span>
                ) : (
                  <span> — {log.action}</span>
                )}
              </div>
            );
          })
        )}
        <div className="text-[#27C93F]">akshay@sentinelai ~ % <span className="inline-block w-2 h-4 bg-white animate-pulse ml-1 align-middle" /></div>
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function formatTimeAgo(iso: string) {
  const sec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} hr ago`;
  return `${Math.floor(sec / 86400)} d ago`;
}
