"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import type { AuditLogEntry } from "@/lib/api";

interface AgentTerminalProps {
  logs: AuditLogEntry[];
  isLoading?: boolean;
  className?: string;
  maxHeight?: string;
}

export function AgentTerminal({
  logs,
  isLoading,
  className,
  maxHeight = "240px",
}: AgentTerminalProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  const isFlex = maxHeight === "100%";

  return (
    <div
      className={cn(
        "rounded-lg border border-[#2d2d2d] overflow-hidden bg-[#1E1E1E] flex flex-col",
        isFlex && "min-h-0",
        className
      )}
    >
      {/* Title bar - Terminal.app style */}
      <div className="flex items-center h-7 px-3 bg-[#3C3C3C] gap-2 shrink-0">
        <div className="flex gap-1.5">
          <div className="w-3 h-3 rounded-full bg-[#FF5F56]" />
          <div className="w-3 h-3 rounded-full bg-[#FFBD2E]" />
          <div className="w-3 h-3 rounded-full bg-[#27C93F]" />
        </div>
        <span className="text-xs text-gray-400 mx-auto">SentinelAI Terminal</span>
      </div>
      {/* Body */}
      <div
        className={cn(
          "p-4 font-mono text-[14px] leading-relaxed overflow-y-auto",
          isFlex && "flex-1 min-h-0"
        )}
        style={isFlex ? undefined : { maxHeight }}
      >
        <div className="space-y-0.5">
          <div className="text-[#27C93F]">
            user@sentinelai ~ %{" "}
            <span className="inline-block w-2 h-4 bg-white animate-pulse ml-0.5" />
          </div>
          {isLoading && logs.length === 0 && (
            <div className="text-gray-500">Waiting for agent activity...</div>
          )}
          {logs.length === 0 && !isLoading && (
            <div className="text-gray-500">No recent activity</div>
          )}
          {logs.map((log) => {
            const ts = log.timestamp
              ? new Date(log.timestamp).toLocaleTimeString("en-GB", {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })
              : "--:--:--";
            return (
              <div key={log.id} className="text-[#D4D4D4]">
                <span className="text-[#6A9955]">[{ts}]</span>
                <span className="text-[#DCDCAA]"> ▶ </span>
                <span className="text-[#569CD6]">{log.agent_name}</span>{" "}
                <span>{log.action}</span>
                {log.tool_name && (
                  <span className="text-[#4EC9B0]"> → {log.tool_name}</span>
                )}
              </div>
            );
          })}
        <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
