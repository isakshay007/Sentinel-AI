"use client";

import { createContext, useCallback, useContext, useState } from "react";

type InjectFaultContextType = {
  isOpen: boolean;
  open: () => void;
  close: () => void;
};

const InjectFaultContext = createContext<InjectFaultContextType | null>(null);

export function InjectFaultProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => setIsOpen(false), []);

  return (
    <InjectFaultContext.Provider value={{ isOpen, open, close }}>
      {children}
    </InjectFaultContext.Provider>
  );
}

export function useInjectFault() {
  const ctx = useContext(InjectFaultContext);
  if (!ctx) throw new Error("useInjectFault must be used within InjectFaultProvider");
  return ctx;
}

