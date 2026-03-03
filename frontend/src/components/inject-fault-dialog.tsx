"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { useInjectFault } from "@/contexts/inject-fault-context";
import { api } from "@/lib/api";
import { AlertTriangle, Loader2, Zap } from "lucide-react";
import { toast } from "sonner";

type FaultType =
  | "memory_leak"
  | "cpu_spike"
  | "network_latency"
  | "kill_service"
  | "cache_failure"
  | "concurrent_faults";

interface FaultConfig {
  label: string;
  description: string;
  showTarget: boolean;
  showDuration: boolean;
  showIntensity: boolean;
  defaultIntensity: number;
  defaultDuration: number;
}

const FAULT_CONFIGS: Record<FaultType, FaultConfig> = {
  memory_leak: {
    label: "Memory Leak",
    description:
      "Gradually consume memory to 90%+. Triggers OOM errors, GC thrashing. Fix: restart + scale.",
    showTarget: true,
    showDuration: true,
    showIntensity: true,
    defaultIntensity: 90,
    defaultDuration: 120,
  },
  cpu_spike: {
    label: "CPU Spike",
    description:
      "Max out CPU cores to 90%+. Triggers slow responses, request timeouts. Fix: scale + restart.",
    showTarget: true,
    showDuration: true,
    showIntensity: true,
    defaultIntensity: 90,
    defaultDuration: 60,
  },
  network_latency: {
    label: "Network Latency",
    description:
      "Add delay to all network traffic. Triggers upstream timeouts, extreme response times. Fix: restart + scale.",
    showTarget: true,
    showDuration: true,
    showIntensity: true,
    defaultIntensity: 80,
    defaultDuration: 120,
  },
  kill_service: {
    label: "Kill Service",
    description:
      "Stop the container entirely. Triggers health check failure, dependent service errors. Fix: restart.",
    showTarget: true,
    showDuration: false,
    showIntensity: false,
    defaultIntensity: 0,
    defaultDuration: 0,
  },
  cache_failure: {
    label: "Cache Failure (Redis)",
    description:
      "Stop Redis. All cache-dependent services degrade with connection errors. Fix: restart Redis + flush cache.",
    showTarget: false,
    showDuration: false,
    showIntensity: false,
    defaultIntensity: 0,
    defaultDuration: 0,
  },
  concurrent_faults: {
    label: "Concurrent Faults",
    description:
      "Inject Memory Leak on user-service AND CPU Spike on payment-service simultaneously to test multi-service incident handling.",
    showTarget: false,
    showDuration: false,
    showIntensity: false,
    defaultIntensity: 0,
    defaultDuration: 0,
  },
};

const SERVICES = [
  { value: "user-service", label: "user-service" },
  { value: "payment-service", label: "payment-service" },
  { value: "api-gateway", label: "api-gateway" },
];

export function InjectFaultDialog() {
  const { isOpen, close } = useInjectFault();
  const [service, setService] = useState<string>("user-service");
  const [faultType, setFaultType] = useState<FaultType>("memory_leak");
  const [duration, setDuration] = useState<number>(120);
  const [intensity, setIntensity] = useState<number>(90);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const config = FAULT_CONFIGS[faultType];

  const onFaultTypeChange = (value: FaultType) => {
    setFaultType(value);
    const c = FAULT_CONFIGS[value];
    setIntensity(c.defaultIntensity);
    setDuration(c.defaultDuration || 120);
  };

  const handleInject = async () => {
    setError(null);
    setRunning(true);

    try {
      if (faultType === "concurrent_faults") {
        const [res1, res2] = await Promise.all([
          api.injectFault("user-service", "memory_leak", 90, 120),
          new Promise<Awaited<ReturnType<typeof api.injectFault>>>((resolve) =>
            setTimeout(
              () => resolve(api.injectFault("payment-service", "cpu_spike", 90, 60)),
              500,
            ),
          ),
        ]);
        close();
        window.dispatchEvent(
          new CustomEvent("fault-injected", {
            detail: {
              target: "user-service + payment-service",
              fault: "concurrent (memory_leak + cpu_spike)",
              duration: 120,
              startedAt: Date.now(),
            },
          }),
        );
        toast.warning(
          "Concurrent faults injected: memory_leak on user-service + cpu_spike on payment-service",
        );
      } else {
        const target = faultType === "cache_failure" ? "redis" : service;
        const effDuration = config.showDuration ? duration : 0;
        const effIntensity = config.showIntensity ? intensity : 0;

        const res = await api.injectFault(target, faultType, effIntensity, effDuration);
        close();
        window.dispatchEvent(
          new CustomEvent("fault-injected", {
            detail: {
              target: res.target,
              fault: res.fault,
              duration: res.duration,
              startedAt: Date.now(),
            },
          }),
        );
        toast.warning(
          `Fault injected: ${res.fault} on ${res.target}. Watcher will detect the anomaly within 30–60 seconds.`,
        );
      }
    } catch (e) {
      setError((e as Error).message);
      toast.error(`Failed to inject fault: ${(e as Error).message}`);
    } finally {
      setRunning(false);
    }
  };

  const handleClose = () => {
    if (!running) {
      close();
      setError(null);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent className="sm:max-w-lg bg-[#0a0f1e]/90 backdrop-blur-2xl border-slate-700/40 shadow-[0_0_50px_rgba(0,0,0,0.5)] p-0 overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-transparent via-red-500/50 to-transparent" />

        <DialogHeader className="p-6 pb-0">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-lg bg-red-500/10 flex items-center justify-center border border-red-500/20">
              <Zap className="h-5 w-5 text-red-500 animate-pulse" />
            </div>
            <div>
              <DialogTitle className="text-[16px] font-black uppercase tracking-[0.25em] text-white">Manual Fault Injection</DialogTitle>
              <p className="text-[10px] font-bold uppercase tracking-wider text-red-500/70">System Authorization Required</p>
            </div>
          </div>
          <DialogDescription className="text-slate-400 text-xs leading-relaxed font-medium">
            Execute controlled stressors on active nodes to validate SentinelAI&apos;s adaptive response and agent collaboration protocols.
          </DialogDescription>
        </DialogHeader>

        <div className="p-6 space-y-6">
          {error && (
            <div className="bg-red-500/10 border border-red-500/20 p-3 rounded-lg flex items-center gap-3 animate-shake">
              <AlertTriangle className="h-4 w-4 text-red-500 shrink-0" />
              <p className="text-[11px] font-bold text-red-400 uppercase tracking-wide">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            {/* Fault Type */}
            <div className="space-y-2">
              <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">Tests</label>
              <Select
                value={faultType}
                onValueChange={(v) => onFaultTypeChange(v as FaultType)}
                disabled={running}
              >
                <SelectTrigger className="bg-slate-950/50 border-slate-800/60 h-10 text-xs font-bold uppercase tracking-wider">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[#0a0f1e] border-slate-800 shadow-2xl">
                  {(Object.keys(FAULT_CONFIGS) as FaultType[]).map((key) => (
                    <SelectItem key={key} value={key} className="text-xs font-bold uppercase tracking-wider focus:bg-red-500/10 focus:text-red-400">
                      {FAULT_CONFIGS[key].label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Target Service */}
            {config.showTarget ? (
              <div className="space-y-2">
                <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">Target Operation</label>
                <Select value={service} onValueChange={setService} disabled={running}>
                  <SelectTrigger className="bg-slate-950/50 border-slate-800/60 h-10 text-xs font-bold uppercase tracking-wider">
                    <SelectValue placeholder="Select service" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#0a0f1e] border-slate-800 shadow-2xl">
                    {SERVICES.map((s) => (
                      <SelectItem key={s.value} value={s.value} className="text-xs font-bold uppercase tracking-wider focus:bg-blue-500/10 focus:text-blue-400">
                        {s.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : (
              <div className="space-y-2">
                <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">Auto-Target</label>
                <div className="h-10 flex items-center px-3 rounded-md bg-slate-950/30 border border-slate-800/40 text-[11px] font-mono text-slate-500 uppercase">
                  {faultType === "cache_failure" ? "redis-cluster" : "multi-node"}
                </div>
              </div>
            )}
          </div>

          <div className="p-4 rounded-xl bg-slate-950/50 border border-slate-800/50 relative overflow-hidden group">
            <div className="absolute inset-0 bg-gradient-to-br from-red-500/5 via-transparent to-transparent opacity-50" />
            <p className="text-[10px] font-black uppercase tracking-widest text-slate-500 mb-2 relative z-10">Description</p>
            <p className="text-[11px] leading-relaxed text-slate-300 font-medium relative z-10">
              {config.description}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            {/* Intensity */}
            {config.showIntensity && (
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">Intensity</label>
                  <span className="text-[11px] font-black tabular-nums text-red-500">{intensity}%</span>
                </div>
                <input
                  type="range"
                  min={1}
                  max={100}
                  value={intensity}
                  onChange={(e) => setIntensity(Number(e.target.value))}
                  disabled={running}
                  className="w-full accent-red-500 h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer slider-red-fill"
                  style={{ "--range-progress": `${intensity}%` } as React.CSSProperties}
                />
              </div>
            )}

            {/* Duration */}
            {config.showDuration && (
              <div className="space-y-2">
                <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">Execution Phase</label>
                <Select
                  value={String(duration)}
                  onValueChange={(v) => setDuration(Number(v))}
                  disabled={running}
                >
                  <SelectTrigger className="bg-slate-950/50 border-slate-800/60 h-10 text-xs font-bold uppercase tracking-wider tabular-nums">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-[#0a0f1e] border-slate-800 shadow-2xl">
                    <SelectItem value="30" className="text-xs font-bold">30s Burst</SelectItem>
                    <SelectItem value="60" className="text-xs font-bold">60s Sustained</SelectItem>
                    <SelectItem value="120" className="text-xs font-bold">120s Prolonged</SelectItem>
                    <SelectItem value="180" className="text-xs font-bold">180s Critical</SelectItem>
                    <SelectItem value="300" className="text-xs font-bold">300s Maximum</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="bg-slate-950/50 p-6 border-t border-slate-800/50 gap-3">
          <Button variant="ghost" onClick={handleClose} disabled={running} className="text-[11px] font-black uppercase tracking-widest text-slate-500 hover:text-white hover:bg-white/5 h-11 px-6">
            Abort
          </Button>
          <Button
            onClick={handleInject}
            disabled={running}
            className="bg-red-600 hover:bg-red-500 text-white h-11 px-8 rounded-lg text-[11px] font-black uppercase tracking-[0.2em] shadow-[0_0_20px_rgba(220,38,38,0.3)] transition-all duration-300 hover:scale-[1.02] active:scale-[0.98]"
          >
            {running ? (
              <Loader2 className="h-4 w-4 animate-spin mr-3" />
            ) : (
              <Zap className="h-4 w-4 mr-3" />
            )}
            {running ? "Executing Phase..." : "Authorize Injection"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
