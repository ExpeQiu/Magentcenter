import type { Metadata } from "next";
import { EntryGate } from "@/components/auth/entry-gate";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentCenter",
  description: "OpenClaw Agent 编排控制台",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen antialiased">
        <EntryGate>{children}</EntryGate>
      </body>
    </html>
  );
}
