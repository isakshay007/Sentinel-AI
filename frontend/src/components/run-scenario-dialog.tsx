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
import { useRunScenario } from "@/contexts/run-scenario-context";
import { usePipeline } from "@/contexts/pipeline-context";
import { useTerminalWindows } from "@/contexts/terminal-windows-context";
import { api } from "@/lib/api";
import { Play, Loader2 } from "lucide-react";
import { toast } from "sonner";

const SCENARIOS = [
  { value: "memory_leak", label: "Memory Leak", service: "user-service" },
  { value: "bad_deployment", label: "Bad Deployment", service: "payment-service" },
  { value: "api_timeout", label: "API Timeout", service: "api-gateway" },
];

export function RunScenarioDialog() {
  const { isOpen, close } = useRunScenario();
  const { startPipeline, completePipeline, resetPipeline } = usePipeline();
  const { openPipelineTerminal, setPipelineResult } = useTerminalWindows();
  const [scenario, setScenario] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRun = async () => {
    if (!scenario) return;
    const s = SCENARIOS.find((x) => x.value === scenario);
    if (!s) return;

    setError(null);
    setRunning(true);

    startPipeline(s.service, s.value);
    close();
    const terminalId = openPipelineTerminal(s.value, s.service);
    toast.info("Pipeline started — terminal opening with live output");

    try {
      const res = await api.runScenario(scenario);
      completePipeline(res);
      setPipelineResult(terminalId, res);
      window.dispatchEvent(
        new CustomEvent("scenario-completed", {
          detail: {
            incidentId: res.incident_id,
            pendingApprovals: res.pending_approvals,
          },
        })
      );
      const pending = (res as { pending_approvals?: number }).pending_approvals ?? 0;
      if (pending > 0) {
        toast.success(`Pipeline complete — incident created. ${pending} action(s) need approval.`);
      } else {
        toast.success("Pipeline complete — incident created");
      }
    } catch (e) {
      resetPipeline();
      setPipelineResult(terminalId, { error: (e as Error).message });
      toast.error(`Pipeline failed: ${(e as Error).message}`);
    } finally {
      setRunning(false);
      setScenario("");
    }
  };

  const handleClose = () => {
    if (!running) {
      close();
      setError(null);
      setScenario("");
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Run Scenario</DialogTitle>
          <DialogDescription>
            Trigger the AI pipeline (Watcher → Diagnostician → Strategist). A terminal window will
            open with live output.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          {error && (
            <p className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">{error}</p>
          )}
          <div className="space-y-2">
            <label className="text-sm font-medium">Scenario</label>
            <Select value={scenario} onValueChange={setScenario} disabled={running}>
              <SelectTrigger>
                <SelectValue placeholder="Select scenario" />
              </SelectTrigger>
              <SelectContent>
                {SCENARIOS.map((s) => (
                  <SelectItem key={s.value} value={s.value}>
                    {s.label} ({s.service})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={running}>
            Cancel
          </Button>
          <Button
            onClick={handleRun}
            disabled={running || !scenario}
            className="bg-black hover:bg-black/90"
          >
            {running ? (
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
            ) : (
              <Play className="h-4 w-4 mr-2" />
            )}
            Run Pipeline
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
