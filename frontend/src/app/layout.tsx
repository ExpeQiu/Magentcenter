import type { Metadata, Viewport } from "next";
import { EntryGate } from "@/components/auth/entry-gate";
import { PwaRegister } from "@/components/pwa-register";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentCenter",
  description: "OpenClaw Agent 编排控制台",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "AgentCenter",
  },
};

export const viewport: Viewport = {
  themeColor: "#0f1419",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
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
        <PwaRegister />
      </body>
    </html>
  );
}
