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
import { Loader2, Zap } from "lucide-react";
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
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Inject Fault</DialogTitle>
          <DialogDescription>
            Break a real service to test SentinelAI&apos;s live incident response. The Watcher
            will detect anomalies and trigger the full agent pipeline automatically.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          {error && (
            <p className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">{error}</p>
          )}

          {/* Fault Type */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Fault Type</label>
            <Select
              value={faultType}
              onValueChange={(v) => onFaultTypeChange(v as FaultType)}
              disabled={running}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(FAULT_CONFIGS) as FaultType[]).map((key) => (
                  <SelectItem key={key} value={key}>
                    {FAULT_CONFIGS[key].label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{config.description}</p>
          </div>

          {/* Target Service */}
          {config.showTarget && (
            <div className="space-y-2">
              <label className="text-sm font-medium">Target Service</label>
              <Select value={service} onValueChange={setService} disabled={running}>
                <SelectTrigger>
                  <SelectValue placeholder="Select service" />
                </SelectTrigger>
                <SelectContent>
                  {SERVICES.map((s) => (
                    <SelectItem key={s.value} value={s.value}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {!config.showTarget && faultType === "cache_failure" && (
            <div className="space-y-2">
              <label className="text-sm font-medium">Target</label>
              <div className="rounded-md border px-3 py-2 text-sm text-muted-foreground bg-muted/50">
                redis (automatic)
              </div>
            </div>
          )}

          {faultType === "concurrent_faults" && (
            <div className="rounded-md border px-3 py-2 text-sm space-y-1 bg-muted/30">
              <p className="font-medium">Will inject two faults:</p>
              <p className="text-muted-foreground">
                1. Memory Leak on <span className="font-mono">user-service</span> (intensity: 90,
                duration: 120s)
              </p>
              <p className="text-muted-foreground">
                2. CPU Spike on <span className="font-mono">payment-service</span> (intensity: 90,
                duration: 60s)
              </p>
            </div>
          )}

          {/* Intensity */}
          {config.showIntensity && (
            <div className="space-y-2">
              <label className="text-sm font-medium">
                Intensity{" "}
                <span className="text-muted-foreground font-normal">({intensity})</span>
              </label>
              <input
                type="range"
                min={1}
                max={100}
                value={intensity}
                onChange={(e) => setIntensity(Number(e.target.value))}
                disabled={running}
                className="w-full accent-primary"
              />
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>1</span>
                <span>50</span>
                <span>100</span>
              </div>
            </div>
          )}

          {/* Duration */}
          {config.showDuration && (
            <div className="space-y-2">
              <label className="text-sm font-medium">Duration (seconds)</label>
              <Select
                value={String(duration)}
                onValueChange={(v) => setDuration(Number(v))}
                disabled={running}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="30">30s</SelectItem>
                  <SelectItem value="60">60s</SelectItem>
                  <SelectItem value="120">120s</SelectItem>
                  <SelectItem value="180">180s</SelectItem>
                  <SelectItem value="300">300s</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          <p className="text-xs text-amber-600 bg-amber-100/60 border border-amber-200 px-3 py-2 rounded-md">
            This will actually break the target service in Docker. The AI agents will detect and
            respond automatically within 30–60 seconds.
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={running}>
            Cancel
          </Button>
          <Button
            onClick={handleInject}
            disabled={running}
            className="bg-black hover:bg-black/90 text-white shrink-0"
          >
            {running ? (
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
            ) : (
              <Zap className="h-4 w-4 mr-2" />
            )}
            {running ? "Injecting..." : "Inject Fault"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
