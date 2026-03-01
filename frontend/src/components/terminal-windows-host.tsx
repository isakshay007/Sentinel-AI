"use client";

import { useTerminalWindows } from "@/contexts/terminal-windows-context";
import { TerminalWindow } from "@/components/terminal-window";

export function TerminalWindowsHost() {
  const { windows } = useTerminalWindows();
  const visible = windows.filter((w) => w.visible).sort((a, b) => a.zIndex - b.zIndex);

  return (
    <>
      {visible.map((win) => (
        <TerminalWindow key={win.id} window={win} />
      ))}
    </>
  );
}
