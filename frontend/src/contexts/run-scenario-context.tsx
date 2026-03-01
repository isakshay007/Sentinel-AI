"use client";

import { createContext, useContext, useState, useCallback } from "react";

type RunScenarioContextType = {
  isOpen: boolean;
  open: () => void;
  close: () => void;
};

const RunScenarioContext = createContext<RunScenarioContextType | null>(null);

export function RunScenarioProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => setIsOpen(false), []);
  return (
    <RunScenarioContext.Provider value={{ isOpen, open, close }}>
      {children}
    </RunScenarioContext.Provider>
  );
}

export function useRunScenario() {
  const ctx = useContext(RunScenarioContext);
  if (!ctx) throw new Error("useRunScenario must be used within RunScenarioProvider");
  return ctx;
}
