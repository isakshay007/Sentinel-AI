"use client";

import { createContext, useContext, useState, useCallback } from "react";
import type { RunScenarioResponse } from "@/lib/api";

type PipelineContextType = {
  isRunning: boolean;
  startedAt: number | null;
  result: RunScenarioResponse | null;
  service: string | null;
  scenario: string | null;
  startPipeline: (service: string, scenario: string) => void;
  completePipeline: (result: RunScenarioResponse) => void;
  resetPipeline: () => void;
};

const PipelineContext = createContext<PipelineContextType | null>(null);

export function PipelineProvider({ children }: { children: React.ReactNode }) {
  const [isRunning, setIsRunning] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [result, setResult] = useState<RunScenarioResponse | null>(null);
  const [service, setService] = useState<string | null>(null);
  const [scenario, setScenario] = useState<string | null>(null);

  const startPipeline = useCallback((svc: string, scen: string) => {
    setIsRunning(true);
    setStartedAt(Date.now());
    setResult(null);
    setService(svc);
    setScenario(scen);
  }, []);

  const completePipeline = useCallback((res: RunScenarioResponse) => {
    setIsRunning(false);
    setResult(res);
  }, []);

  const resetPipeline = useCallback(() => {
    setIsRunning(false);
    setStartedAt(null);
    setResult(null);
    setService(null);
    setScenario(null);
  }, []);

  return (
    <PipelineContext.Provider
      value={{
        isRunning,
        startedAt,
        result,
        service,
        scenario,
        startPipeline,
        completePipeline,
        resetPipeline,
      }}
    >
      {children}
    </PipelineContext.Provider>
  );
}

export function usePipeline() {
  const ctx = useContext(PipelineContext);
  if (!ctx) throw new Error("usePipeline must be used within PipelineProvider");
  return ctx;
}
