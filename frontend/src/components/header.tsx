"use client";

import { useEffect, useState, useCallback } from "react";
import { usePathname } from "next/navigation";
import { Zap, FlaskConical, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useInjectFault } from "@/contexts/inject-fault-context";
import { api } from "@/lib/api";

const PAGE_TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/incidents": "Incidents",
  "/approvals": "Approvals",
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function Header() {
  const { open } = useInjectFault();
  const pathname = usePathname();
  const [evalTime, setEvalTime] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  const fetchEval = useCallback(() => {
    api.getEvalStatus().then((r) => {
      if (r.has_results && r.timestamp) setEvalTime(r.timestamp);
    }).catch(() => { });
  }, []);

  useEffect(() => {
    fetchEval();
    const id = setInterval(fetchEval, 60_000);
    return () => clearInterval(id);
  }, [fetchEval]);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const status = await api.getEvalStatus();
      if (status.has_results) {
        const blob = new Blob([JSON.stringify(status, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "sentinel_eval_results.json";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }
    } catch {
      // Silent fail
    } finally {
      setDownloading(false);
    }
  };

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

      <div className="flex items-center gap-3">
        {/* Eval download button */}
        {evalTime && (
          <button
            onClick={handleDownload}
            disabled={downloading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-500/5 border border-emerald-500/20 hover:border-emerald-500/40 transition-all duration-300 cursor-pointer group disabled:opacity-50"
          >
            <FlaskConical className="h-3 w-3 text-emerald-500 group-hover:text-emerald-400" />
            <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-500/80 group-hover:text-emerald-400">
              Last eval: {timeAgo(evalTime)}
            </span>
            <Download className="h-2.5 w-2.5 text-emerald-500/60 group-hover:text-emerald-400 ml-0.5" />
          </button>
        )}

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
      </div>
    </header>
  );
}
