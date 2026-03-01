"use client";

import { createContext, useContext, useState, useCallback } from "react";
import type { AuditLogEntry } from "@/lib/api";

export type TerminalType = "pipeline" | "agent" | "activity";

export type TerminalWindowState = {
  id: string;
  title: string;
  type: TerminalType;
  visible: boolean; // false = closed (data preserved)
  position: { x: number; y: number };
  size: { width: number; height: number };
  minimized: boolean;
  maximized: boolean;
  zIndex: number;
  // Content data (preserved when closed)
  pipeline?: { scenario: string; service: string; lines: string[]; startedAt: number | null; result: unknown };
  agent?: { agentId: string; agentName: string; decisions: unknown[] };
  activity?: { logs: AuditLogEntry[] };
};

type TerminalWindowsContextType = {
  windows: TerminalWindowState[];
  openPipelineTerminal: (scenario: string, service: string) => string;
  openAgentTerminal: (agentId: string, agentName: string) => string;
  openActivityTerminal: () => string;
  closeTerminal: (id: string) => void;
  hideTerminal: (id: string) => void;
  showTerminal: (id: string) => void;
  focusTerminal: (id: string) => void;
  updateTerminal: (id: string, updates: Partial<TerminalWindowState>) => void;
  updatePipelineLines: (id: string, lines: string[]) => void;
  appendPipelineLine: (id: string, line: string) => void;
  setPipelineResult: (id: string, result: unknown) => void;
  setAgentDecisions: (id: string, decisions: unknown[]) => void;
  setActivityLogs: (id: string, logs: AuditLogEntry[]) => void;
  toggleMinimize: (id: string) => void;
  toggleMaximize: (id: string) => void;
};

const DEFAULT_SIZE = { width: 640, height: 420 };

let nextZ = 1;
function getNextZ() {
  return nextZ++;
}

const TerminalWindowsContext = createContext<TerminalWindowsContextType | null>(null);

export function TerminalWindowsProvider({ children }: { children: React.ReactNode }) {
  const [windows, setWindows] = useState<TerminalWindowState[]>([]);

  const focusTerminal = useCallback((id: string) => {
    setWindows((prev) =>
      prev.map((w) => (w.id === id ? { ...w, zIndex: getNextZ() } : w))
    );
  }, []);

  const openPipelineTerminal = useCallback((scenario: string, service: string) => {
    const scenarioLabel = { memory_leak: "Memory Leak", bad_deployment: "Bad Deployment", api_timeout: "API Timeout" }[scenario] || scenario;
    const title = `Pipeline — ${scenarioLabel}`;
    const newId = `term-pipeline-${Date.now()}`;
    setWindows((prev) => [
      ...prev,
      {
        id: newId,
        title,
        type: "pipeline",
        visible: true,
        position: { x: 80 + prev.filter((w) => w.visible).length * 30, y: 80 + prev.filter((w) => w.visible).length * 30 },
        size: { ...DEFAULT_SIZE },
        minimized: false,
        maximized: false,
        zIndex: getNextZ(),
        pipeline: {
          scenario,
          service,
          lines: [`run-pipeline --service ${service} --scenario ${scenario}`, "", `[${new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}] ▶ Phase 1: Watcher starting...`],
          startedAt: Date.now(),
          result: null,
        },
      },
    ]);
    return newId;
  }, []);

  const openAgentTerminal = useCallback(
    (agentId: string, agentName: string) => {
      const title = `${agentName} Agent`;
      const existing = windows.find((w) => w.visible && w.type === "agent" && w.agent?.agentId === agentId);
      if (existing) {
        focusTerminal(existing.id);
        return existing.id;
      }
      const closed = windows.find((w) => !w.visible && w.type === "agent" && w.agent?.agentId === agentId);
      if (closed) {
        setWindows((prev) =>
          prev.map((w) =>
            w.id === closed.id
              ? { ...w, visible: true, zIndex: getNextZ(), agent: { ...w.agent!, agentId, agentName } }
              : w
          )
        );
        return closed.id;
      }
      const newId = `term-agent-${agentId}-${Date.now()}`;
      setWindows((prev) => [
        ...prev,
        {
          id: newId,
          title,
          type: "agent",
          visible: true,
          position: { x: 80 + prev.filter((w) => w.visible).length * 30, y: 80 + prev.filter((w) => w.visible).length * 30 },
          size: { ...DEFAULT_SIZE },
          minimized: false,
          maximized: false,
          zIndex: getNextZ(),
          agent: { agentId, agentName, decisions: [] },
        },
      ]);
      return newId;
    },
    [windows, focusTerminal]
  );

  const openActivityTerminal = useCallback(() => {
    const existing = windows.find((w) => w.visible && w.type === "activity");
    if (existing) {
      focusTerminal(existing.id);
      return existing.id;
    }
    const closed = windows.find((w) => !w.visible && w.type === "activity");
    if (closed) {
      setWindows((prev) =>
        prev.map((w) =>
          w.id === closed.id ? { ...w, visible: true, zIndex: getNextZ() } : w
        )
      );
      return closed.id;
    }
    const newId = `term-activity-${Date.now()}`;
    setWindows((prev) => [
      ...prev,
      {
        id: newId,
        title: "Activity Log",
        type: "activity",
        visible: true,
        position: { x: 80 + prev.filter((w) => w.visible).length * 30, y: 80 + prev.filter((w) => w.visible).length * 30 },
        size: { ...DEFAULT_SIZE },
        minimized: false,
        maximized: false,
        zIndex: getNextZ(),
        activity: { logs: [] },
      },
    ]);
    return newId;
  }, [windows, focusTerminal]);

  const closeTerminal = useCallback((id: string) => {
    setWindows((prev) => prev.map((w) => (w.id === id ? { ...w, visible: false } : w)));
  }, []);

  const hideTerminal = closeTerminal;

  const showTerminal = useCallback((id: string) => {
    setWindows((prev) =>
      prev.map((w) => (w.id === id ? { ...w, visible: true, zIndex: getNextZ() } : w))
    );
  }, []);

  const updateTerminal = useCallback((id: string, updates: Partial<TerminalWindowState>) => {
    setWindows((prev) => prev.map((w) => (w.id === id ? { ...w, ...updates } : w)));
  }, []);

  const updatePipelineLines = useCallback((id: string, lines: string[]) => {
    setWindows((prev) =>
      prev.map((w) =>
        w.id === id && w.pipeline ? { ...w, pipeline: { ...w.pipeline, lines } } : w
      )
    );
  }, []);

  const appendPipelineLine = useCallback((id: string, line: string) => {
    setWindows((prev) =>
      prev.map((w) =>
        w.id === id && w.pipeline
          ? { ...w, pipeline: { ...w.pipeline, lines: [...w.pipeline.lines, line] } }
          : w
      )
    );
  }, []);

  const setPipelineResult = useCallback((id: string, result: unknown) => {
    setWindows((prev) =>
      prev.map((w) =>
        w.id === id && w.pipeline ? { ...w, pipeline: { ...w.pipeline, result } } : w
      )
    );
  }, []);

  const setAgentDecisions = useCallback((id: string, decisions: unknown[]) => {
    setWindows((prev) =>
      prev.map((w) =>
        w.id === id && w.agent ? { ...w, agent: { ...w.agent, decisions } } : w
      )
    );
  }, []);

  const setActivityLogs = useCallback((id: string, logs: AuditLogEntry[]) => {
    setWindows((prev) =>
      prev.map((w) =>
        w.id === id && w.activity ? { ...w, activity: { ...w.activity, logs } } : w
      )
    );
  }, []);

  const toggleMinimize = useCallback((id: string) => {
    setWindows((prev) =>
      prev.map((w) => (w.id === id ? { ...w, minimized: !w.minimized, maximized: false } : w))
    );
  }, []);

  const toggleMaximize = useCallback((id: string) => {
    setWindows((prev) =>
      prev.map((w) => (w.id === id ? { ...w, maximized: !w.maximized } : w))
    );
  }, []);

  return (
    <TerminalWindowsContext.Provider
      value={{
        windows,
        openPipelineTerminal,
        openAgentTerminal,
        openActivityTerminal,
        closeTerminal,
        hideTerminal,
        showTerminal,
        focusTerminal,
        updateTerminal,
        updatePipelineLines,
        appendPipelineLine,
        setPipelineResult,
        setAgentDecisions,
        setActivityLogs,
        toggleMinimize,
        toggleMaximize,
      }}
    >
      {children}
    </TerminalWindowsContext.Provider>
  );
}

export function useTerminalWindows() {
  const ctx = useContext(TerminalWindowsContext);
  if (!ctx) throw new Error("useTerminalWindows must be used within TerminalWindowsProvider");
  return ctx;
}
