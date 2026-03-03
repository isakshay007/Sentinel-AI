import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/components/theme-provider";
import { Sidebar } from "@/components/sidebar";
import { Header } from "@/components/header";
import { InjectFaultProvider } from "@/contexts/inject-fault-context";
import { PipelineProvider } from "@/contexts/pipeline-context";
import { TerminalWindowsProvider } from "@/contexts/terminal-windows-context";
import { InjectFaultDialog } from "@/components/inject-fault-dialog";
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
  title: "SentinelAI — Autonomous Incident Response",
  description: "Real-time AI-powered DevOps incident detection, diagnosis, and remediation",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning className="dark">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-[#0a0f1e]`}
      >
        <ThemeProvider>
          <TooltipProvider delayDuration={200}>
            <InjectFaultProvider>
              <PipelineProvider>
                <TerminalWindowsProvider>
                  <div className="flex min-h-screen">
                    <Sidebar />
                    <div className="flex-1 flex flex-col min-w-0 ml-[230px]">
                      <Header />
                      <main className="flex-1 px-5 py-4 overflow-auto">{children}</main>
                    </div>
                  </div>
                  <InjectFaultDialog />
                  <TerminalWindowsHost />
                  <Toaster
                    position="bottom-right"
                    richColors
                    closeButton
                    theme="dark"
                    toastOptions={{
                      style: {
                        background: "#111827",
                        border: "1px solid #1e293b",
                        color: "#e2e8f0",
                        borderRadius: "10px",
                        fontSize: "12px",
                      },
                    }}
                  />
                </TerminalWindowsProvider>
              </PipelineProvider>
            </InjectFaultProvider>
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
