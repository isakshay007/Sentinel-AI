import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/components/theme-provider";
import { Sidebar } from "@/components/sidebar";
import { Header } from "@/components/header";
import { RunScenarioProvider } from "@/contexts/run-scenario-context";
import { PipelineProvider } from "@/contexts/pipeline-context";
import { TerminalWindowsProvider } from "@/contexts/terminal-windows-context";
import { RunScenarioDialog } from "@/components/run-scenario-dialog";
import { TerminalWindowsHost } from "@/components/terminal-windows-host";
import { Toaster } from "sonner";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "SentinelAI — Human-AI Incident Response",
  description: "Autonomous DevOps incident response platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <ThemeProvider>
          <TooltipProvider>
            <RunScenarioProvider>
              <PipelineProvider>
                <TerminalWindowsProvider>
                  <div className="flex min-h-screen">
                    <Sidebar />
                    <div className="flex-1 flex flex-col">
                      <Header />
                      <main className="flex-1 p-8 overflow-auto">{children}</main>
                    </div>
                  </div>
                  <RunScenarioDialog />
                  <TerminalWindowsHost />
                  <Toaster position="bottom-right" richColors closeButton />
                </TerminalWindowsProvider>
              </PipelineProvider>
            </RunScenarioProvider>
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
