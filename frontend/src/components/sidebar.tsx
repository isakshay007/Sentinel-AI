"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  AlertTriangle,
  FlaskConical,
  Shield,
  CheckSquare,
  ScrollText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { api } from "@/lib/api";
import { useTerminalWindows } from "@/contexts/terminal-windows-context";

const navItems = [
  { href: "/", icon: LayoutDashboard, label: "Dashboard" },
  { href: "/incidents", icon: AlertTriangle, label: "Incidents" },
  { href: "/evaluations", icon: FlaskConical, label: "Evaluations" },
  { href: "/safety", icon: Shield, label: "Safety" },
];

export function Sidebar() {
  const pathname = usePathname();
  const [pendingCount, setPendingCount] = useState(0);
  const { openActivityTerminal } = useTerminalWindows();

  const refreshPending = () => {
    api.getApprovals().then((r) => setPendingCount(r.total_pending)).catch(() => {});
  };

  useEffect(() => {
    refreshPending();
    const id = setInterval(refreshPending, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    window.addEventListener("approvals-updated", refreshPending);
    window.addEventListener("scenario-completed", refreshPending);
    return () => {
      window.removeEventListener("approvals-updated", refreshPending);
      window.removeEventListener("scenario-completed", refreshPending);
    };
  }, []);

  return (
    <aside className="w-56 border-r border-[#E5E7EB] dark:border-border bg-white dark:bg-card flex flex-col min-h-screen shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
      <div className="p-4 h-14 flex items-center">
        <span className="text-[13px] font-medium text-muted-foreground">Navigation</span>
      </div>
      <Separator />
      <nav className="flex-1 p-2 space-y-0.5">
        {navItems.map((item) => {
          const isActive = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link key={item.href} href={item.href}>
              <Button
                variant={isActive ? "secondary" : "ghost"}
                className={cn(
                  "w-full justify-start gap-2",
                  isActive && "bg-accent"
                )}

              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </Button>
            </Link>
          );
        })}
        <Separator className="my-2" />
        <Button
          variant="ghost"
          className="w-full justify-start gap-2"
          onClick={() => openActivityTerminal()}
        >
          <ScrollText className="h-4 w-4" />
          Logs
        </Button>
        <Separator className="my-2" />
        <Link href="/approvals">
          <Button
            variant={pathname === "/approvals" ? "secondary" : "ghost"}
            className="w-full justify-start gap-2"
          >
            <CheckSquare className="h-4 w-4" />
            Approvals
            {pendingCount > 0 && (
              <Badge variant="destructive" className="ml-auto h-5 px-1.5">
                {pendingCount}
              </Badge>
            )}
          </Button>
        </Link>
      </nav>
    </aside>
  );
}

