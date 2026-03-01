"use client";

import { useTheme } from "next-themes";
import { Moon, Sun, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useRunScenario } from "@/contexts/run-scenario-context";

export function Header() {
  const { theme, setTheme } = useTheme();
  const { open: openRunScenario } = useRunScenario();

  return (
    <header className="h-14 border-b border-[#E5E7EB] dark:border-border flex items-center px-6 bg-white dark:bg-card shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
      <div className="flex-1 flex items-center gap-4">
        <span className="text-lg font-semibold text-foreground">SentinelAI</span>
        <span className="text-sm text-muted-foreground hidden sm:inline">
          Human-AI Incident Response Workspace
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        >
          <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
          <Moon className="h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
          <span className="sr-only">Toggle theme</span>
        </Button>
        <Button
          onClick={openRunScenario}
          className="bg-black hover:bg-black/90 text-white shrink-0"
        >
          <Play className="h-4 w-4 mr-2" />
          Run Scenario
        </Button>
      </div>
    </header>
  );
}
