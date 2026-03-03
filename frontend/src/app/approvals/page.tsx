"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type ApprovalRequest } from "@/lib/api";
import { Check, X, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);

  const fetchApprovals = () => {
    api
      .getApprovals()
      .then((r) => setApprovals(r.approvals))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchApprovals();
  }, []);

  useEffect(() => {
    const handler = () => fetchApprovals();
    window.addEventListener("approvals-updated", handler);
    window.addEventListener("scenario-completed", handler);
    window.addEventListener("execution-completed", handler);
    const id = setInterval(fetchApprovals, 5000);
    return () => {
      window.removeEventListener("approvals-updated", handler);
      window.removeEventListener("scenario-completed", handler);
      window.removeEventListener("execution-completed", handler);
      clearInterval(id);
    };
  }, []);

  const handleApprove = async (req: ApprovalRequest) => {
    setProcessing(req.id);
    try {
      const res = await api.approve(req.id);
      setRemovingId(req.id);
      toast.success(res.incident_resolved ? `Action approved and incident resolved: ${req.action}` : `Action approved and executed: ${req.action}`);
      setTimeout(() => {
        setApprovals((prev) => prev.filter((a) => a.id !== req.id));
        setRemovingId(null);
        window.dispatchEvent(new CustomEvent("approvals-updated"));
        window.dispatchEvent(new CustomEvent("execution-completed", { detail: { incident_id: res.incident_id, incident_resolved: res.incident_resolved } }));
      }, 300);
    } catch {
      toast.error("Failed to approve");
    } finally {
      setProcessing(null);
    }
  };

  const handleReject = async (req: ApprovalRequest) => {
    setProcessing(req.id);
    try {
      await api.reject(req.id);
      setRemovingId(req.id);
      toast.success(`Action rejected: ${req.action}`);
      setTimeout(() => {
        setApprovals((prev) => prev.filter((a) => a.id !== req.id));
        setRemovingId(null);
        window.dispatchEvent(new CustomEvent("approvals-updated"));
      }, 300);
    } catch {
      toast.error("Failed to reject");
    } finally {
      setProcessing(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px] text-muted-foreground text-[15px]">
        Loading...
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <h1 className="text-page-title">Pending Approvals</h1>

      {approvals.length === 0 ? (
        <Card className="shadow-[0_1px_2px_rgba(0,0,0,0.05)] border-[#E5E7EB]">
          <CardContent className="py-16 text-center">
            <CheckCircle2 className="h-12 w-12 text-emerald-500 mx-auto mb-4" />
            <p className="text-[18px] font-semibold text-foreground mb-2">
              No pending approvals. All clear.
            </p>
            <p className="text-[15px] text-muted-foreground">
              Inject a fault to trigger agent responses. Risky actions will appear here for approval.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {approvals.map((req) => (
            <Card
              key={req.id}
              className={cn(
                "shadow-[0_1px_2px_rgba(0,0,0,0.05)] border-[#E5E7EB] transition-all duration-300",
                req.risk_level === "dangerous" && "border-red-500/50",
                removingId === req.id && "opacity-0 translate-x-4 pointer-events-none"
              )}
            >
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">{req.action}</CardTitle>
                  <Badge
                    variant={
                      req.risk_level === "dangerous"
                        ? "destructive"
                        : req.risk_level === "risky"
                          ? "default"
                          : "secondary"
                    }
                  >
                    {req.risk_level.toUpperCase()}
                  </Badge>
                </div>
                <p className="text-[14px] text-muted-foreground">
                  Requested by: {req.agent_name} • Service: {req.service}
                </p>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-2 mt-4">
                  <Button
                    size="sm"
                    onClick={() => handleApprove(req)}
                    disabled={processing === req.id}
                    className="bg-emerald-600 hover:bg-emerald-700"
                  >
                    <Check className="h-4 w-4 mr-1" />
                    Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => handleReject(req)}
                    disabled={processing === req.id}
                  >
                    <X className="h-4 w-4 mr-1" />
                    Reject
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
