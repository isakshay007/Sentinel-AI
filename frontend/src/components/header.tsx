"use client";

import { usePathname } from "next/navigation";
import { Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useInjectFault } from "@/contexts/inject-fault-context";

const PAGE_TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/incidents": "Incidents",
  "/approvals": "Approvals",
};

export function Header() {
  const { open } = useInjectFault();
  const pathname = usePathname();

  const title = Object.entries(PAGE_TITLES).find(
    ([path]) => pathname === path || (path !== "/" && pathname.startsWith(path))
  )?.[1] ?? "Dashboard";

  return (
    <header className="h-14 border-b border-white/[0.03] flex items-center justify-between px-6 bg-[#0a0f1e]/60 backdrop-blur-2xl shrink-0 sticky top-0 z-30">
      <div className="flex flex-col">
        <h1 className="text-[14px] font-black text-white/90 tracking-[0.25em] uppercase drop-shadow-[0_0_8px_rgba(255,255,255,0.1)]">
          {title}
        </h1>
      </div>

      <Button
        onClick={open}
        size="sm"
        className="group relative overflow-hidden bg-transparent border border-red-500/30 hover:border-red-500/60 text-red-500 px-5 gap-2 h-8 text-[11px] font-black uppercase tracking-widest rounded-lg transition-all duration-300 hover:shadow-[0_0_20px_rgba(239,68,68,0.3)]"
      >
        <div className="absolute inset-0 bg-red-500/5 group-hover:bg-red-500/10 transition-colors" />
        <div className="absolute left-0 top-0 bottom-0 w-[2px] bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.8)]" />
        <Zap className="h-3 w-3 relative z-10 animate-pulse" />
        <span className="relative z-10">Inject Fault</span>
      </Button>
    </header>
  );
}
